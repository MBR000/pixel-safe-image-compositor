#!/usr/bin/env python3
"""Preflight validator for pixel-safe-image-compositor.

Validates composition-plan.json and the protected-region mask BEFORE any AI
generation. Organic modes (subject_cutout, organic_context) are rejected with
exit code 1 when the mask contains forbidden geometry: rectangles, unbroken
contours, or long straight edges.

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

MODES = ("subject_cutout", "organic_context", "photo_window")
ORGANIC_MODES = ("subject_cutout", "organic_context")

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
    "preview_review",
)

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
)

# Geometry thresholds for organic modes.
MAX_STRAIGHT_EDGE_RATIO = 0.12   # of the longest protected-region dimension
RECTANGULARITY_ERROR = 0.90      # mask_area / bbox_area above this = rectangle
RECTANGULARITY_WARN = 0.75
MIN_QUIET_BUFFER_PX = 8
CONTOUR_BROKEN_MIN = 0.20        # min fraction of boundary rows/cols that must vary
SAWTOOTH_REGULARITY_ERROR = 0.90  # periodic zigzag match fraction above this
PHOTO_WINDOW_RECT_MIN = 0.98     # photo_window masks must be near-rectangular


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

    return {
        "area_px": area,
        "bbox": {"width": bbox_w, "height": bbox_h},
        "rectangularity": round(area / bbox_area, 4) if bbox_area else 0.0,
        "longest_dim_px": longest_dim,
        "straight_edge_limit_px": round(MAX_STRAIGHT_EDGE_RATIO * longest_dim, 2),
        "max_straight_horizontal_px": max_h,
        "max_straight_vertical_px": max_v,
        "max_straight_diagonal_px": max_d,
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

    review = plan.get("preview_review") or {}
    for f in REQUIRED_REVIEW_FIELDS:
        if f not in review:
            errors.append("preview_review missing field: %s" % f)
        elif review[f] is not True:
            errors.append(
                "preview_review.%s must be true, got %r" % (f, review[f]))
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
