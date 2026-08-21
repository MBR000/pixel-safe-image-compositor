#!/usr/bin/env python3
"""Preflight validator for pixel-safe-image-compositor.

Validates composition-plan.json and the protected-region mask BEFORE any AI
generation. Organic modes (subject_cutout, organic_context) are rejected with
exit code 1 when the mask contains forbidden geometry: rectangles, unbroken
contours, or long straight edges. photo_echo masks must run full-bleed to the
canvas edges with a single organic torn seam.

Usage:
    python preflight_composition.py \
        --plan composition-plan.json \
        --mask mask.png \
        --out composition.preflight.json \
        [--mask-preview mask-preview.png]

Exit codes: 0 = verified, 1 = validation errors, 2 = usage/IO error.
"""

import argparse
import json
import sys

import numpy as np
from PIL import Image, ImageDraw

MODES = ("subject_cutout", "organic_context", "photo_window", "photo_echo")
ORGANIC_MODES = ("subject_cutout", "organic_context")
SEAM_SIDES = ("left", "right", "top", "bottom")

REQUIRED_PLAN_FIELDS = (
    "mode",
    "focal_group",
    "eye_path",
    "keep_context",
    "drop_context",
    "source_shape_candidates",
    "selected_shape",
    "source_crop",
    "placement",
    "layout_budget",
    "window",
    "edge_profile",
    "transition",
    "fusion",
    "atmosphere",
    "preview_review_requirements",
)

# Fusion plan: where colors come from, where transitions attach, and how
# material continuity works. Forces the AI to plan blending, not just
# avoid forbidden artifacts.
REQUIRED_FUSION_LIST_FIELDS = ("source_palette_cues", "transition_anchors")
REQUIRED_FUSION_TEXT_FIELDS = ("material_continuity", "transition_density")

# Atmosphere plan: the editorial-collage design layer (adapted from the
# gathered-scenes zine approach). All tactile treatments live OUTSIDE the
# protected pixels.
ILLUSTRATION_GRAMMARS = ("silhouette_led", "contour_led", "field_led",
                         "rhythm_led", "cut_paper_led")
EDGE_TREATMENTS = ("torn_paper_fibrous", "soft_fiber_fringe", "smooth_curve")
CHROMA_INTEGRATION_MODES = ("source_continuation", "selective_replacement",
                            "underprint_passage", "counterform",
                            "directional_rhythm")
ILLUSTRATION_FIELD_SHARE_RANGE = (0.25, 0.80)
QUIET_SHARE_RANGE = (0.45, 0.90)
MICRO_TEXT_MAX_EN_WORDS = 5
MICRO_TEXT_MAX_CJK_CHARS = 8

REQUIRED_EDGE_FIELDS = (
    "construction",
    "smoothing",
    "variation_scales",
    "quiet_buffer_px",
    "no_sawtooth",
    "detached_transition",
)

REQUIRED_REVIEW_FIELDS = (
    "keep_context_complete",
    "selected_shape_readable_at_thumbnail",
    "no_closed_outline",
    "no_uniform_halo",
    "no_sawtooth",
    "quiet_buffer_visible",
    "detached_transition_shapes",
    "quiet_space_supports_eye_path",
    "shape_serves_motion",
    "no_default_oval_island",
)

DESIGN_SHAPE_LANGUAGES = (
    "motion_brush",
    "leaf_sweep",
    "wedge_sweep",
    "counterform",
    "contour_echo",
)

# Geometry thresholds for organic modes.
MAX_STRAIGHT_EDGE_RATIO = 0.12   # of the longest protected-region dimension
RECTANGULARITY_ERROR = 0.90      # mask_area / bbox_area above this = rectangle
RECTANGULARITY_WARN = 0.75
MIN_QUIET_BUFFER_PX = 8
CONTOUR_BROKEN_MIN = 0.20        # min fraction of boundary rows/cols that must vary
SAWTOOTH_REGULARITY_ERROR = 0.90  # periodic zigzag match fraction above this
PHOTO_WINDOW_RECT_MIN = 0.98     # photo_window masks must be near-rectangular

# Perceptual-rectangle gate: a shape reads as a rectangle when it is fairly
# full, all four bbox corners are occupied, AND every side hugs the bbox
# line on average - even if the edges wobble. All three must hold.
VISUAL_RECT_RECTANGULARITY_MIN = 0.70
VISUAL_RECT_CORNER_OCCUPANCY_MIN = 0.85
VISUAL_RECT_SIDE_INSET_MAX = 0.06  # mean inset / perpendicular bbox dim
CORNER_WINDOW_RATIO = 0.15         # corner sample window as fraction of bbox

# Arbitrary-angle near-straight edge detection (tolerant chord fit).
ANY_ANGLE_TOL_PX = 1.0
MAX_ANY_ANGLE_RATIO = 0.15       # of the longest protected-region dimension

# photo_echo: the protected photo runs full-bleed to canvas edges and the
# remaining boundary is a single organic torn seam along a content line.
# Boundary segments that hug the canvas border are exempt from straightness
# checks; the interior seam must still read as a hand-torn edge.
BORDER_HUG_TOL_PX = 1
BORDER_SIDE_MIN_FRACTION = 0.90   # side reported as full-bleed above this
BORDER_BLEED_MIN_FRACTION = 0.25  # min fraction of canvas perimeter covered
SEAM_SEGMENT_MIN_PX = 16          # ignore tiny interior slivers
SEAM_VARIATION_MIN_PX = 48        # variation check needs a real seam length


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def longest_constant_run(seq):
    """Longest run of identical consecutive values (straight H/V edge)."""
    best = run = 1
    for i in range(1, len(seq)):
        run = run + 1 if seq[i] == seq[i - 1] else 1
        best = max(best, run)
    return best if len(seq) else 0


def longest_slope_run(seq, step):
    """Longest run with constant difference == step (diagonal edge)."""
    best = run = 1
    for i in range(1, len(seq)):
        run = run + 1 if seq[i] - seq[i - 1] == step else 1
        best = max(best, run)
    return best if len(seq) else 0


def longest_tolerant_line(seq, tol=ANY_ANGLE_TOL_PX):
    """Longest near-straight segment at ANY angle, within tol px of a chord.

    Catches shallow diagonals (e.g. 1 px per 4 rows) and jittered long edges
    that evade the exact horizontal/vertical/45-degree run detectors. Binary
    search on the segment length; a window qualifies when every point lies
    within tol of the straight chord between its endpoints.
    """
    a = np.asarray(seq, dtype=float)
    n = len(a)
    if n < 3:
        return n

    windows = np.lib.stride_tricks.sliding_window_view

    def any_window_straight(length):
        win = windows(a, length)
        t = np.linspace(0.0, 1.0, length)
        chord = win[:, :1] + (win[:, -1:] - win[:, :1]) * t
        return bool((np.abs(win - chord).max(axis=1) <= tol).any())

    lo, hi = 2, n
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if any_window_straight(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


def modal_fraction(seq):
    """Fraction of entries equal to the most common value."""
    if not len(seq):
        return 0.0
    values, counts = np.unique(seq, return_counts=True)
    return float(counts.max() / len(seq))


def sawtooth_regularity(seq):
    """Detect a regular periodic zigzag in a boundary sequence.

    Looks for a period p such that the first differences repeat with high
    fidelity AND oscillate in both directions (up-down spikes). Smooth curves
    and plain straight edges do not qualify: straight edges have single-sign
    or zero differences, and smooth curves are not exactly periodic.

    Returns (period, match_fraction); (0, 0.0) when no regular zigzag exists.
    """
    diffs = np.diff(np.asarray(seq))
    n = len(diffs)
    if n < 16:
        return 0, 0.0
    # A sawtooth keeps moving; sparse noise on a flat edge does not count.
    if np.count_nonzero(diffs) / n < 0.5:
        return 0, 0.0
    best_period, best_frac = 0, 0.0
    for p in range(2, min(64, n // 4) + 1):
        window = diffs[:p]
        if window.min() >= 0 or window.max() <= 0:
            continue
        frac = float(np.mean(diffs[p:] == diffs[:-p]))
        if frac > best_frac:
            best_period, best_frac = p, frac
    return best_period, best_frac


def boundary_sequences(mask):
    """Per-row left/right and per-column top/bottom boundary sequences."""
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    left, right = [], []
    for r in np.nonzero(rows)[0]:
        xs = np.nonzero(mask[r])[0]
        left.append(int(xs.min()))
        right.append(int(xs.max()))
    top, bottom = [], []
    for c in np.nonzero(cols)[0]:
        ys = np.nonzero(mask[:, c])[0]
        top.append(int(ys.min()))
        bottom.append(int(ys.max()))
    return left, right, top, bottom


def analyze_mask(mask):
    """Compute geometry metrics for a boolean mask."""
    ys, xs = np.nonzero(mask)
    bbox_w = int(xs.max() - xs.min() + 1)
    bbox_h = int(ys.max() - ys.min() + 1)
    area = int(mask.sum())
    bbox_area = bbox_w * bbox_h
    longest_dim = max(bbox_w, bbox_h)

    left, right, top, bottom = boundary_sequences(mask)

    max_h = max(longest_constant_run(top), longest_constant_run(bottom))
    max_v = max(longest_constant_run(left), longest_constant_run(right))
    max_d = max(
        longest_slope_run(top, 1), longest_slope_run(top, -1),
        longest_slope_run(bottom, 1), longest_slope_run(bottom, -1),
        longest_slope_run(left, 1), longest_slope_run(left, -1),
        longest_slope_run(right, 1), longest_slope_run(right, -1),
    )

    saw_side, saw_period, saw_frac = "", 0, 0.0
    for side, seq in (("left", left), ("right", right),
                      ("top", top), ("bottom", bottom)):
        period, frac = sawtooth_regularity(seq)
        if frac > saw_frac:
            saw_side, saw_period, saw_frac = side, period, frac

    any_side, any_run = "", 0
    for side, seq in (("left", left), ("right", right),
                      ("top", top), ("bottom", bottom)):
        run = longest_tolerant_line(seq)
        if run > any_run:
            any_side, any_run = side, run

    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    sub = mask[y0:y1 + 1, x0:x1 + 1]
    cw = max(2, int(round(bbox_w * CORNER_WINDOW_RATIO)))
    ch = max(2, int(round(bbox_h * CORNER_WINDOW_RATIO)))
    corner_occupancy = float(np.mean([
        sub[:ch, :cw].mean(), sub[:ch, -cw:].mean(),
        sub[-ch:, :cw].mean(), sub[-ch:, -cw:].mean(),
    ]))
    side_inset_ratios = {
        "left": float(np.mean(np.asarray(left) - x0)) / bbox_w,
        "right": float(np.mean(x1 - np.asarray(right))) / bbox_w,
        "top": float(np.mean(np.asarray(top) - y0)) / bbox_h,
        "bottom": float(np.mean(y1 - np.asarray(bottom))) / bbox_h,
    }
    max_side_inset = max(side_inset_ratios.values())
    rectangularity = round(area / bbox_area, 4) if bbox_area else 0.0
    visual_rectangle = bool(
        rectangularity >= VISUAL_RECT_RECTANGULARITY_MIN
        and corner_occupancy >= VISUAL_RECT_CORNER_OCCUPANCY_MIN
        and max_side_inset <= VISUAL_RECT_SIDE_INSET_MAX)

    return {
        "area_px": area,
        "bbox": {"width": bbox_w, "height": bbox_h},
        "rectangularity": rectangularity,
        "corner_occupancy": round(corner_occupancy, 4),
        "side_inset_ratios": {k: round(v, 4)
                              for k, v in side_inset_ratios.items()},
        "max_side_inset_ratio": round(max_side_inset, 4),
        "visual_rectangle": visual_rectangle,
        "longest_dim_px": longest_dim,
        "straight_edge_limit_px": round(MAX_STRAIGHT_EDGE_RATIO * longest_dim, 2),
        "max_straight_horizontal_px": max_h,
        "max_straight_vertical_px": max_v,
        "max_straight_diagonal_px": max_d,
        "any_angle_limit_px": round(MAX_ANY_ANGLE_RATIO * longest_dim, 2),
        "max_straight_any_angle_px": {"side": any_side, "run_px": any_run},
        "contour_variation": {
            "left": round(1.0 - modal_fraction(left), 4),
            "right": round(1.0 - modal_fraction(right), 4),
            "top": round(1.0 - modal_fraction(top), 4),
            "bottom": round(1.0 - modal_fraction(bottom), 4),
        },
        "sawtooth": {
            "side": saw_side,
            "period_px": saw_period,
            "match_fraction": round(saw_frac, 4),
        },
    }


def border_nearness(side, seq, shape):
    """Boolean array: which boundary entries hug the canvas border."""
    h, w = shape
    a = np.asarray(seq)
    if side in ("left", "top"):
        return a <= BORDER_HUG_TOL_PX
    if side == "right":
        return a >= w - 1 - BORDER_HUG_TOL_PX
    return a >= h - 1 - BORDER_HUG_TOL_PX  # bottom


def interior_segments(seq, near_border):
    """Split a boundary sequence into contiguous non-border (seam) segments."""
    segments, current = [], []
    for value, near in zip(seq, near_border):
        if near:
            if current:
                segments.append(current)
                current = []
        else:
            current.append(value)
    if current:
        segments.append(current)
    return segments


def check_photo_echo(mask, metrics, seam_plan, errors):
    """Validate photo_echo geometry: full-bleed borders + one organic seam.

    Boundary entries lying on the canvas border are exempt from all
    straightness checks - that is the point of full-bleed. Every interior
    boundary segment (the torn seam) must read as a hand-torn edge: no long
    straight or near-straight runs, no regular sawtooth, real variation.
    """
    h, w = mask.shape
    perimeter = 2 * (h + w)
    bleed = float(mask[0, :].sum() + mask[-1, :].sum()
                  + mask[:, 0].sum() + mask[:, -1].sum()) / perimeter

    left, right, top, bottom = boundary_sequences(mask)
    sides = {"left": left, "right": right, "top": top, "bottom": bottom}

    hug, seam_sides = {}, []
    for side, seq in sides.items():
        near = border_nearness(side, seq, mask.shape)
        frac = float(near.mean()) if len(seq) else 0.0
        hug[side] = round(frac, 4)
        if frac < BORDER_SIDE_MIN_FRACTION:
            seam_sides.append(side)

    if bleed < BORDER_BLEED_MIN_FRACTION:
        errors.append(
            "photo_echo requires the protected photo to run full-bleed to "
            "the canvas edges (only %.0f%% of the canvas perimeter is "
            "covered, need >= %.0f%%); for a floating shape use an organic "
            "mode instead" % (bleed * 100, BORDER_BLEED_MIN_FRACTION * 100))
    if not seam_sides:
        errors.append(
            "photo_echo mask is full-bleed on all four canvas edges; no "
            "torn seam remains for the illustration layer")

    declared = seam_plan.get("side")
    if declared in sides and declared not in seam_sides:
        errors.append(
            "plan declares seam.side=%r but that boundary hugs the canvas "
            "border (hug fraction %.2f); the torn seam must be an interior "
            "boundary" % (declared, hug.get(declared, 0.0)))

    limit = metrics["straight_edge_limit_px"]
    any_limit = metrics["any_angle_limit_px"]
    seam_metrics = {}
    for side, seq in sides.items():
        near = border_nearness(side, seq, mask.shape)
        segments = [s for s in interior_segments(seq, near)
                    if len(s) >= SEAM_SEGMENT_MIN_PX]
        if not segments:
            continue
        max_straight = max_any = 0
        saw_frac = 0.0
        interior_vals = []
        for seg in segments:
            max_straight = max(max_straight, longest_constant_run(seg),
                               longest_slope_run(seg, 1),
                               longest_slope_run(seg, -1))
            max_any = max(max_any, longest_tolerant_line(seg))
            saw_frac = max(saw_frac, sawtooth_regularity(seg)[1])
            interior_vals.extend(seg)
        variation = round(1.0 - modal_fraction(interior_vals), 4)
        seam_metrics[side] = {
            "seam_px": len(interior_vals),
            "max_straight_px": max_straight,
            "max_any_angle_px": max_any,
            "sawtooth_match_fraction": round(saw_frac, 4),
            "variation": variation,
        }
        if max_straight > limit:
            errors.append(
                "photo_echo seam on %s side has a straight run of %d px "
                "exceeding limit %.1f px; the tear must be an organic curve"
                % (side, max_straight, limit))
        if max_any > any_limit:
            errors.append(
                "photo_echo seam on %s side has a near-straight segment of "
                "%d px (tolerance %.1f px) exceeding limit %.1f px"
                % (side, max_any, ANY_ANGLE_TOL_PX, any_limit))
        if saw_frac >= SAWTOOTH_REGULARITY_ERROR:
            errors.append(
                "photo_echo seam on %s side is a regular sawtooth "
                "(regularity %.2f >= %.2f); regular tears are forbidden"
                % (side, saw_frac, SAWTOOTH_REGULARITY_ERROR))
        if (len(interior_vals) >= SEAM_VARIATION_MIN_PX
                and variation < CONTOUR_BROKEN_MIN):
            errors.append(
                "photo_echo seam on %s side barely varies (variation %.3f "
                "< %.2f); a flat seam is not a torn edge"
                % (side, variation, CONTOUR_BROKEN_MIN))

    return {
        "border_bleed_fraction": round(bleed, 4),
        "edge_hug": hug,
        "seam_sides": sorted(seam_sides),
        "seams": seam_metrics,
    }


def micro_text_too_long(text):
    """True when the micro-text exceeds 8 CJK chars or 5 English words."""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    if cjk:
        return cjk > MICRO_TEXT_MAX_CJK_CHARS
    return len(text.split()) > MICRO_TEXT_MAX_EN_WORDS


def validate_atmosphere(atm, errors):
    """Validate the editorial-atmosphere design layer of the plan."""
    grammar = atm.get("illustration_grammar")
    if grammar not in ILLUSTRATION_GRAMMARS:
        errors.append("atmosphere.illustration_grammar must be one of %s, "
                      "got %r" % (", ".join(ILLUSTRATION_GRAMMARS), grammar))

    subjects = atm.get("photo_echo_subjects")
    if (not isinstance(subjects, list) or not subjects
            or not all(isinstance(s, str) and s.strip() for s in subjects)):
        errors.append(
            "atmosphere.photo_echo_subjects must be a non-empty list of "
            "concrete photo elements the illustration layer redraws (e.g. "
            "'rider silhouette', 'lake horizon'); generic doodles unrelated "
            "to the photo are forbidden")

    share = atm.get("illustration_field_share")
    lo, hi = ILLUSTRATION_FIELD_SHARE_RANGE
    if not isinstance(share, (int, float)) or isinstance(share, bool) \
            or not lo <= share <= hi:
        errors.append(
            "atmosphere.illustration_field_share must be a number in "
            "[%.2f, %.2f] (a timid peripheral doodle is not a field), "
            "got %r" % (lo, hi, share))

    quiet = atm.get("quiet_share")
    lo, hi = QUIET_SHARE_RANGE
    if not isinstance(quiet, (int, float)) or isinstance(quiet, bool) \
            or not lo <= quiet <= hi:
        errors.append("atmosphere.quiet_share must be a number in "
                      "[%.2f, %.2f], got %r" % (lo, hi, quiet))

    texture = atm.get("quiet_texture")
    if not isinstance(texture, str) or not texture.strip():
        errors.append(
            "atmosphere.quiet_texture must describe the low-contrast "
            "material of the quiet zones (washes, halftone grain, paper "
            "fiber); quiet space is textured material, not blank paper")

    edge = atm.get("edge_treatment")
    if edge not in EDGE_TREATMENTS:
        errors.append("atmosphere.edge_treatment must be one of %s, got %r"
                      % (", ".join(EDGE_TREATMENTS), edge))

    accent = atm.get("chromatic_accent")
    if not isinstance(accent, dict):
        errors.append("atmosphere.chromatic_accent must be an object with "
                      "hue, integration_mode, structural_role")
    else:
        hue = accent.get("hue")
        if not isinstance(hue, str) or not hue.strip():
            errors.append("atmosphere.chromatic_accent.hue must be an exact, "
                          "non-empty color description")
        mode = accent.get("integration_mode")
        if mode not in CHROMA_INTEGRATION_MODES:
            errors.append(
                "atmosphere.chromatic_accent.integration_mode must be one "
                "of %s, got %r"
                % (", ".join(CHROMA_INTEGRATION_MODES), mode))
        role = accent.get("structural_role")
        if not isinstance(role, str) or not role.strip():
            errors.append(
                "atmosphere.chromatic_accent.structural_role must explain "
                "what compositional work the hue does (removal test)")

    if "micro_text" not in atm:
        errors.append("atmosphere.micro_text is required (use null to opt "
                      "out of text explicitly)")
    else:
        micro = atm["micro_text"]
        if micro is not None:
            if not isinstance(micro, dict):
                errors.append("atmosphere.micro_text must be null or an "
                              "object with text and placement")
            else:
                text = micro.get("text")
                if not isinstance(text, str) or not text.strip():
                    errors.append(
                        "atmosphere.micro_text.text must be a non-empty "
                        "string")
                elif micro_text_too_long(text.strip()):
                    errors.append(
                        "atmosphere.micro_text.text exceeds limits (max %d "
                        "English words or %d Han characters): %r"
                        % (MICRO_TEXT_MAX_EN_WORDS, MICRO_TEXT_MAX_CJK_CHARS,
                           text))
                placement = micro.get("placement")
                if not isinstance(placement, str) or not placement.strip():
                    errors.append(
                        "atmosphere.micro_text.placement must name a quiet-"
                        "paper area outside the protected region")


def validate_design_intent(intent, errors, warnings):
    """Require an authored shape direction, not just a safe blob."""
    if not isinstance(intent, dict):
        errors.append(
            "design_intent must be an object describing the visual logic "
            "of the protected shape")
        return
    language = intent.get("shape_language")
    if language not in DESIGN_SHAPE_LANGUAGES:
        errors.append(
            "design_intent.shape_language must be one of %s, got %r; "
            "generic oval/island is not a design direction"
            % (", ".join(DESIGN_SHAPE_LANGUAGES), language))
    for field in ("motion_axis", "leading_mass", "trailing_taper",
                  "rationale"):
        value = intent.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(
                "design_intent.%s must be a non-empty design explanation"
                % field)
    budget = intent.get("protected_context_budget")
    if (not isinstance(budget, (int, float)) or isinstance(budget, bool)
            or not 0.10 <= budget <= 0.60):
        errors.append(
            "design_intent.protected_context_budget must be a number in "
            "[0.10, 0.60], got %r" % budget)
    if language == "counterform" and "negative_space_role" not in intent:
        warnings.append(
            "counterform shape should explain the negative-space role")


def validate_plan(plan, errors, warnings):
    missing = [f for f in REQUIRED_PLAN_FIELDS if f not in plan]
    if missing:
        errors.append("missing plan fields: %s" % ", ".join(missing))
        return None

    mode = plan.get("mode")
    if mode not in MODES:
        errors.append("mode must be one of %s, got %r" % (list(MODES), mode))

    window = plan.get("window") or {}
    wtype = window.get("type")
    if mode == "photo_window":
        if wtype != "rectangle_mask":
            errors.append(
                "photo_window requires window.type=rectangle_mask, got %r" % wtype)
    elif wtype == "rectangle_mask":
        errors.append(
            "window.type=rectangle_mask is only allowed with mode=photo_window")
    if mode == "photo_echo":
        if wtype != "torn_seam":
            errors.append(
                "photo_echo requires window.type=torn_seam, got %r" % wtype)
    elif wtype == "torn_seam":
        errors.append(
            "window.type=torn_seam is only allowed with mode=photo_echo")

    if mode == "photo_echo":
        seam = plan.get("seam")
        if not isinstance(seam, dict):
            errors.append(
                "photo_echo requires a seam object with anchor and side")
        else:
            anchor = seam.get("anchor")
            if not isinstance(anchor, str) or not anchor.strip():
                errors.append(
                    "seam.anchor must name the source content line the tear "
                    "follows (e.g. 'lake horizon', 'mountain ridge') so the "
                    "photo and the illustration stay continuous across it")
            if seam.get("side") not in SEAM_SIDES:
                errors.append("seam.side must be one of %s, got %r"
                              % (", ".join(SEAM_SIDES), seam.get("side")))

    edge = plan.get("edge_profile") or {}
    for f in REQUIRED_EDGE_FIELDS:
        if f not in edge:
            errors.append("edge_profile missing field: %s" % f)
    scales = edge.get("variation_scales") or {}
    for s in ("large", "medium", "small"):
        if s not in scales:
            errors.append("edge_profile.variation_scales missing: %s" % s)
        elif scales[s] is not True:
            errors.append(
                "edge_profile.variation_scales.%s must be true, got %r"
                % (s, scales[s]))
    if edge.get("no_sawtooth") is not True:
        errors.append("edge_profile.no_sawtooth must be true")
    if edge.get("detached_transition") is not True:
        errors.append("edge_profile.detached_transition must be true")
    qbuf = edge.get("quiet_buffer_px")
    if not isinstance(qbuf, int) or qbuf <= 0:
        errors.append("edge_profile.quiet_buffer_px must be a positive integer")
    elif qbuf < MIN_QUIET_BUFFER_PX:
        warnings.append("quiet_buffer_px=%d is below recommended %d"
                        % (qbuf, MIN_QUIET_BUFFER_PX))

    fusion = plan.get("fusion") or {}
    for f in REQUIRED_FUSION_LIST_FIELDS:
        v = fusion.get(f)
        if (not isinstance(v, list) or not v
                or not all(isinstance(s, str) and s.strip() for s in v)):
            errors.append(
                "fusion.%s must be a non-empty list of strings" % f)
    for f in REQUIRED_FUSION_TEXT_FIELDS:
        v = fusion.get(f)
        if not isinstance(v, str) or not v.strip():
            errors.append("fusion.%s must be a non-empty string" % f)

    validate_atmosphere(plan.get("atmosphere") or {}, errors)
    if "design_intent" in plan:
        validate_design_intent(plan.get("design_intent"), errors, warnings)
    else:
        warnings.append(
            "legacy plan has no design_intent; new plans must declare a "
            "directional shape language, motion axis, leading mass, and "
            "trailing taper")

    review = plan.get("preview_review_requirements") or {}
    for f in REQUIRED_REVIEW_FIELDS:
        if f not in review:
            errors.append(
                "preview_review_requirements missing field: %s" % f)
        elif review[f] is not True:
            errors.append(
                "preview_review_requirements.%s must be true, got %r"
                % (f, review[f]))
    return mode


def write_mask_preview(mask, path, source=None):
    """Render the mask with its bbox (red) for visual inspection.

    Without --source: white mask on black. With --source: the protected
    region shows the actual source pixels at full brightness and the rest
    of the canvas shows the source dimmed, so the reviewer sees exactly
    which content survives.
    """
    if source is not None:
        src = np.asarray(source.convert("RGB"), dtype=np.float32)
        vis = (src * 0.30).astype(np.uint8)
        vis[mask] = src[mask].astype(np.uint8)
    else:
        vis = np.zeros((mask.shape[0], mask.shape[1], 3), dtype=np.uint8)
        vis[mask] = (255, 255, 255)
    img = Image.fromarray(vis)
    draw = ImageDraw.Draw(img)
    ys, xs = np.nonzero(mask)
    draw.rectangle([xs.min(), ys.min(), xs.max(), ys.max()],
                   outline=(220, 40, 40))
    img.save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plan", required=True, help="composition-plan.json")
    parser.add_argument("--mask", required=True, help="protected-region mask PNG")
    parser.add_argument("--out", required=True, help="JSON report output path")
    parser.add_argument("--mask-preview", default=None,
                        help="optional mask-preview.png output path")
    parser.add_argument("--source", default=None,
                        help="optional source image to overlay in the "
                             "mask preview (must match mask dimensions)")
    args = parser.parse_args()

    errors, warnings = [], []

    try:
        plan = load_json(args.plan)
    except (OSError, json.JSONDecodeError) as exc:
        print("cannot read plan: %s" % exc, file=sys.stderr)
        return 2

    mode = validate_plan(plan, errors, warnings)

    try:
        mask_img = Image.open(args.mask).convert("L")
    except OSError as exc:
        print("cannot read mask: %s" % exc, file=sys.stderr)
        return 2
    mask_arr = np.asarray(mask_img)
    mask = mask_arr > 127

    gray = int(np.logical_and(mask_arr > 0, mask_arr < 255).sum())
    if gray:
        warnings.append(
            "mask contains %d anti-aliased (non-binary) pixels; preflight "
            "binarizes at >127 but restore_and_verify pastes source alpha>0, "
            "so the approved and restored shapes may differ - use a binary "
            "mask derived from the source cutout alpha" % gray)

    metrics = {}
    if not mask.any():
        errors.append("mask is empty: no protected pixels")
    else:
        metrics = analyze_mask(mask)
        if mode == "photo_window":
            if metrics["rectangularity"] < PHOTO_WINDOW_RECT_MIN:
                errors.append(
                    "photo_window declared but mask is not rectangular "
                    "(rectangularity=%.3f < %.2f)"
                    % (metrics["rectangularity"], PHOTO_WINDOW_RECT_MIN))
        if mode == "photo_echo":
            seam_plan = plan.get("seam") if isinstance(plan.get("seam"),
                                                       dict) else {}
            metrics["photo_echo"] = check_photo_echo(
                mask, metrics, seam_plan, errors)
        if mode in ORGANIC_MODES:
            limit = metrics["straight_edge_limit_px"]
            if metrics["rectangularity"] >= RECTANGULARITY_ERROR:
                errors.append(
                    "mask is rectangular (rectangularity=%.3f >= %.2f); "
                    "rectangles are forbidden outside photo_window"
                    % (metrics["rectangularity"], RECTANGULARITY_ERROR))
            elif metrics["rectangularity"] >= RECTANGULARITY_WARN:
                warnings.append("rectangularity=%.3f is high for an organic mode"
                                % metrics["rectangularity"])
            if metrics["visual_rectangle"]:
                errors.append(
                    "mask is visually rectangular: rectangularity=%.3f, "
                    "corner_occupancy=%.3f >= %.2f, max_side_inset_ratio="
                    "%.3f <= %.2f; wobbly edges on a rectangle still read "
                    "as a rectangle"
                    % (metrics["rectangularity"],
                       metrics["corner_occupancy"],
                       VISUAL_RECT_CORNER_OCCUPANCY_MIN,
                       metrics["max_side_inset_ratio"],
                       VISUAL_RECT_SIDE_INSET_MAX))
            any_angle = metrics["max_straight_any_angle_px"]
            if any_angle["run_px"] > metrics["any_angle_limit_px"]:
                errors.append(
                    "near-straight %s contour segment of %d px at an "
                    "arbitrary angle (tolerance %.1f px) exceeds limit "
                    "%.1f px (%d%% of longest dimension)"
                    % (any_angle["side"], any_angle["run_px"],
                       ANY_ANGLE_TOL_PX, metrics["any_angle_limit_px"],
                       int(MAX_ANY_ANGLE_RATIO * 100)))
            for axis, key in (("horizontal", "max_straight_horizontal_px"),
                              ("vertical", "max_straight_vertical_px"),
                              ("diagonal", "max_straight_diagonal_px")):
                if metrics[key] > limit:
                    errors.append(
                        "%s straight edge of %d px exceeds limit %.1f px "
                        "(12%% of longest dimension)" % (axis, metrics[key], limit))
            for side, frac in metrics["contour_variation"].items():
                if frac < CONTOUR_BROKEN_MIN:
                    errors.append(
                        "%s contour is not broken (variation %.3f < %.2f); "
                        "long unbroken edges are forbidden"
                        % (side, frac, CONTOUR_BROKEN_MIN))
            saw = metrics["sawtooth"]
            if saw["match_fraction"] >= SAWTOOTH_REGULARITY_ERROR:
                errors.append(
                    "regular sawtooth detected on %s contour (period %d px, "
                    "regularity %.2f >= %.2f); regular sawtooth is forbidden"
                    % (saw["side"], saw["period_px"], saw["match_fraction"],
                       SAWTOOTH_REGULARITY_ERROR))

    verified = not errors
    report = {
        "verified": verified,
        "mode": mode,
        "errors": errors,
        "warnings": warnings,
        "mask_metrics": metrics,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")
    print(json.dumps(report, indent=2))

    if args.mask_preview and metrics:
        source = None
        if args.source:
            try:
                source = Image.open(args.source)
            except OSError as exc:
                print("cannot read source for preview: %s" % exc,
                      file=sys.stderr)
            if source is not None and source.size != mask_img.size:
                print("source size %r differs from mask size %r; "
                      "preview falls back to silhouette"
                      % (source.size, mask_img.size), file=sys.stderr)
                source = None
        write_mask_preview(mask, args.mask_preview, source=source)

    return 0 if verified else 1


if __name__ == "__main__":
    sys.exit(main())
