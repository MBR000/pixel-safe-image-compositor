"""End-to-end and unit tests for pixel-safe-image-compositor.

Run from the repository root:

    python -m unittest discover -s tests -v

Requires numpy and Pillow (see requirements.txt).
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "scripts")
sys.path.insert(0, SCRIPTS)

import preflight_composition as pf  # noqa: E402
import smooth_mask as sm  # noqa: E402


def full_plan(mode="subject_cutout", placement=None):
    plan = {
        "mode": mode,
        "focal_group": "subject",
        "eye_path": "top-left to bottom-right",
        "keep_context": [],
        "drop_context": [],
        "source_shape_candidates": ["blob"],
        "selected_shape": "blob",
        "source_crop": {},
        "placement": placement or {"x": 4, "y": 4, "width": 4, "height": 4},
        "layout_budget": {},
        "window": ({"type": "rectangle_mask"} if mode == "photo_window"
                   else {"type": "torn_seam"} if mode == "photo_echo"
                   else {}),
        "transition": {},
        "edge_profile": {
            "construction": "free_curve",
            "smoothing": "chaikin_corner_cutting",
            "variation_scales": {"large": True, "medium": True, "small": True},
            "quiet_buffer_px": 24,
            "no_sawtooth": True,
            "detached_transition": True,
        },
        "fusion": {
            "source_palette_cues": ["warm ochre from the subject"],
            "transition_anchors": ["upper ridge", "lower paper texture"],
            "material_continuity": "paper grain continues across transition",
            "transition_density": "sparse near subject, denser farther away",
        },
        "atmosphere": {
            "illustration_grammar": "field_led",
            "photo_echo_subjects": ["rider silhouette", "lake horizon"],
            "illustration_field_share": 0.55,
            "quiet_share": 0.65,
            "quiet_texture": "pale wash over visible paper grain",
            "edge_treatment": "torn_paper_fibrous",
            "chromatic_accent": {
                "hue": "clean tomato red",
                "integration_mode": "directional_rhythm",
                "structural_role": "route line guides the eye from summit "
                                   "ghost down to the subject",
            },
            "micro_text": {
                "text": "The long ascent",
                "placement": "upper-left quiet paper, typewriter serif",
            },
        },
        "design_intent": {
            "shape_language": "motion_brush",
            "motion_axis": "forward-right",
            "leading_mass": "the dog's head and front legs",
            "trailing_taper": "the tail and rear grass taper back into paper",
            "protected_context_budget": 0.34,
            "rationale": "The protected shape stretches with the running gesture instead of becoming a static oval.",
        },
        "preview_review_requirements": {
            k: True for k in pf.REQUIRED_REVIEW_FIELDS},
    }
    if mode == "photo_echo":
        plan["seam"] = {"anchor": "lake horizon", "side": "top"}
    return plan


def blob_mask(size=300, radius=95):
    """Smooth free-form blob that satisfies all organic geometry limits."""
    yy, xx = np.mgrid[0:size, 0:size].astype(float)
    cy = cx = size / 2.0
    ang = np.arctan2(yy - cy, xx - cx)
    rad = np.hypot(yy - cy, xx - cx)
    wobble = (1.0 + 0.22 * np.sin(3 * ang + 0.7)
              + 0.11 * np.sin(7 * ang + 1.9)
              + 0.06 * np.sin(13 * ang + 4.2)
              + 0.035 * np.sin(23 * ang + 2.2))
    return rad <= radius * wobble


def rect_mask(size=200):
    mask = np.zeros((size, size), dtype=bool)
    mask[40:160, 50:150] = True
    return mask


def straight_edge_mask():
    """Blob with the left side sliced off into a long vertical edge."""
    mask = blob_mask()
    mask[:, :70] = False
    return mask


def sawtooth_mask(size=240):
    """Left edge is a regular triangle wave (period 8, amplitude 12 px)."""
    mask = np.zeros((size, size), dtype=bool)
    for r in range(20, 220):
        t = (r - 20) % 8
        tri = t if t < 4 else 8 - t
        x0 = 40 + 4 * tri
        x1 = 170 + int(18 * np.sin((r - 20) / 31.0))
        mask[r, x0:x1] = True
    return mask


def wavy_rect_mask(size=240):
    """Rectangle with wobbly (inward-waving) edges but occupied corners.

    Rectangularity lands below the 0.90 hard gate, yet the shape still
    reads as a rectangle - the case the perceptual gate must catch.
    """
    mask = np.zeros((size, size), dtype=bool)
    x0, x1, y0, y1 = 30, 210, 30, 210
    span = y1 - y0
    for r in range(y0, y1):
        taper = np.sin(np.pi * (r - y0) / span)  # keeps corners occupied
        wl = 20 * (0.5 + 0.5 * np.sin(2 * np.pi * (r - y0) / 47.0)) * taper
        wr = 20 * (0.5 + 0.5 * np.sin(2 * np.pi * (r - y0) / 61.0 + 1.3)) \
            * taper
        mask[r, x0 + int(wl):x1 - int(wr)] = True
    for c in range(x0, x1):
        taper = np.sin(np.pi * (c - x0) / (x1 - x0))
        wt = 20 * (0.5 + 0.5 * np.sin(2 * np.pi * (c - x0) / 53.0 + 0.5)) \
            * taper
        wb = 20 * (0.5 + 0.5 * np.sin(2 * np.pi * (c - x0) / 71.0 + 2.1)) \
            * taper
        mask[y0:y0 + int(wt), c] = False
        mask[y1 - int(wb):y1, c] = False
    return mask


def shallow_diagonal_mask(size=240):
    """Left edge is a shallow staircase (1 px per 4 rows) - a near-straight
    line at an angle the exact H/V/45-degree detectors cannot see."""
    mask = np.zeros((size, size), dtype=bool)
    for r in range(20, 200):
        xa = 30 + (r - 20) // 4
        xb = 170 + int(14 * np.sin((r - 20) / 9.0))
        mask[r, xa:xb] = True
    return mask


def photo_echo_mask(size=400, straight=False):
    """Bottom region runs full-bleed to the left/right/bottom canvas edges;
    the top boundary is an organic torn seam (or a flat seam when
    straight=True). Models the zine layout: photo below, paper above."""
    mask = np.zeros((size, size), dtype=bool)
    xs = np.arange(size)
    if straight:
        seam = np.full(size, size // 2)
    else:
        env = np.sin(np.pi * xs / (size - 1))  # 0 at both canvas edges
        seam = (190 + 40 * env
                + env * (12 * np.sin(2 * np.pi * xs / 53.0 + 1.3)
                         + 5 * np.sin(2 * np.pi * xs / 19.0 + 0.4))
                ).astype(int)
    for c in range(size):
        mask[seam[c]:, c] = True
    return mask


def save_mask(mask, path):
    Image.fromarray((mask * 255).astype(np.uint8)).save(path)


def run_script(script, *argv):
    proc = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, script)] + list(argv),
        capture_output=True, text=True)
    return proc


class PreflightTests(unittest.TestCase):

    def run_preflight(self, plan, mask, extra=()):
        with tempfile.TemporaryDirectory() as td:
            plan_path = os.path.join(td, "plan.json")
            mask_path = os.path.join(td, "mask.png")
            out_path = os.path.join(td, "report.json")
            with open(plan_path, "w", encoding="utf-8") as fh:
                json.dump(plan, fh)
            save_mask(mask, mask_path)
            proc = run_script("preflight_composition.py",
                              "--plan", plan_path, "--mask", mask_path,
                              "--out", out_path, *extra)
            with open(out_path, "r", encoding="utf-8") as fh:
                report = json.load(fh)
            return proc.returncode, report

    def test_freeform_mask_passes(self):
        rc, report = self.run_preflight(full_plan(), blob_mask())
        self.assertEqual(rc, 0, report["errors"])
        self.assertTrue(report["verified"])

    def test_rectangle_rejected_in_organic_mode(self):
        rc, report = self.run_preflight(full_plan(), rect_mask())
        self.assertEqual(rc, 1)
        self.assertTrue(any("rectangular" in e for e in report["errors"]),
                        report["errors"])

    def test_long_straight_edge_rejected(self):
        rc, report = self.run_preflight(full_plan(), straight_edge_mask())
        self.assertEqual(rc, 1)
        self.assertTrue(any("straight edge" in e for e in report["errors"]),
                        report["errors"])

    def test_regular_sawtooth_rejected(self):
        rc, report = self.run_preflight(full_plan(), sawtooth_mask())
        self.assertEqual(rc, 1)
        self.assertTrue(any("regular sawtooth" in e for e in report["errors"]),
                        report["errors"])

    def test_false_review_values_rejected(self):
        plan = full_plan()
        plan["preview_review_requirements"] = {
            k: False for k in pf.REQUIRED_REVIEW_FIELDS}
        plan["edge_profile"]["variation_scales"]["medium"] = False
        rc, report = self.run_preflight(plan, blob_mask())
        self.assertEqual(rc, 1)
        self.assertTrue(
            any("variation_scales.medium must be true" in e
                for e in report["errors"]), report["errors"])
        review_errors = [e for e in report["errors"]
                         if e.startswith("preview_review_requirements.")]
        self.assertEqual(len(review_errors), len(pf.REQUIRED_REVIEW_FIELDS))

    def test_invalid_fusion_rejected(self):
        plan = full_plan()
        plan["fusion"] = {"source_palette_cues": [],
                          "transition_anchors": "not-a-list",
                          "material_continuity": "",
                          "transition_density": 3}
        rc, report = self.run_preflight(plan, blob_mask())
        self.assertEqual(rc, 1)
        fusion_errors = [e for e in report["errors"]
                         if e.startswith("fusion.")]
        self.assertEqual(len(fusion_errors), 4, report["errors"])

    def test_design_intent_required_and_directional(self):
        plan = full_plan()
        del plan["design_intent"]
        rc, report = self.run_preflight(plan, blob_mask())
        self.assertEqual(rc, 0, report["errors"])
        self.assertTrue(any("legacy plan" in w for w in report["warnings"]),
                        report["warnings"])

        plan = full_plan()
        plan["design_intent"]["shape_language"] = "organic_island"
        rc2, report2 = self.run_preflight(plan, blob_mask())
        self.assertEqual(rc2, 1)
        self.assertTrue(any("shape_language" in e for e in report2["errors"]),
                        report2["errors"])

    def test_invalid_atmosphere_rejected(self):
        plan = full_plan()
        plan["atmosphere"] = {
            "illustration_grammar": "sticker_led",
            "illustration_field_share": 0.05,  # timid peripheral doodle
            "quiet_share": 1.5,
            "edge_treatment": "clean_digital_cut",
            "chromatic_accent": {"hue": "", "integration_mode": "floating",
                                 "structural_role": ""},
        }
        rc, report = self.run_preflight(plan, blob_mask())
        self.assertEqual(rc, 1)
        atm_errors = [e for e in report["errors"]
                      if e.startswith("atmosphere.")]
        # grammar, photo_echo_subjects, field share, quiet share,
        # quiet_texture, edge treatment, hue, integration mode,
        # structural role, missing micro_text
        self.assertEqual(len(atm_errors), 10, report["errors"])

    def test_missing_echo_subjects_and_quiet_texture_rejected(self):
        plan = full_plan()
        del plan["atmosphere"]["photo_echo_subjects"]
        del plan["atmosphere"]["quiet_texture"]
        rc, report = self.run_preflight(plan, blob_mask())
        self.assertEqual(rc, 1)
        self.assertTrue(any("photo_echo_subjects" in e
                            for e in report["errors"]), report["errors"])
        self.assertTrue(any("quiet_texture" in e for e in report["errors"]),
                        report["errors"])

    def test_micro_text_limits(self):
        plan = full_plan()
        plan["atmosphere"]["micro_text"] = {
            "text": "this english line has too many words",
            "placement": "upper-left quiet paper",
        }
        rc, report = self.run_preflight(plan, blob_mask())
        self.assertEqual(rc, 1)
        self.assertTrue(any("micro_text.text exceeds limits" in e
                            for e in report["errors"]), report["errors"])
        # Opting out with null is legal.
        plan["atmosphere"]["micro_text"] = None
        rc2, report2 = self.run_preflight(plan, blob_mask())
        self.assertEqual(rc2, 0, report2["errors"])
        # CJK limit: 9 Han characters is too long, 8 is fine.
        plan["atmosphere"]["micro_text"] = {"text": "翻山越岭的漫长上升",
                                            "placement": "left quiet paper"}
        rc3, report3 = self.run_preflight(plan, blob_mask())
        self.assertEqual(rc3, 1)
        plan["atmosphere"]["micro_text"] = {"text": "漫长的上升",
                                            "placement": "left quiet paper"}
        rc4, report4 = self.run_preflight(plan, blob_mask())
        self.assertEqual(rc4, 0, report4["errors"])

    def test_wavy_rectangle_rejected_as_visual_rectangle(self):
        rc, report = self.run_preflight(full_plan(), wavy_rect_mask())
        self.assertEqual(rc, 1)
        metrics = report["mask_metrics"]
        # The whole point: below the 0.90 hard threshold, yet still caught.
        self.assertLess(metrics["rectangularity"], pf.RECTANGULARITY_ERROR)
        self.assertTrue(metrics["visual_rectangle"], metrics)
        self.assertTrue(any("visually rectangular" in e
                            for e in report["errors"]), report["errors"])

    def test_shallow_diagonal_rejected(self):
        rc, report = self.run_preflight(full_plan(), shallow_diagonal_mask())
        self.assertEqual(rc, 1)
        self.assertTrue(any("arbitrary angle" in e
                            for e in report["errors"]), report["errors"])
        # The exact-slope detectors alone must NOT have caught the left edge:
        metrics = report["mask_metrics"]
        limit = metrics["straight_edge_limit_px"]
        self.assertLessEqual(metrics["max_straight_vertical_px"], limit,
                             metrics)

    def test_longest_tolerant_line_unit(self):
        shallow = [30 + i // 4 for i in range(160)]  # slope 1/4 staircase
        self.assertGreaterEqual(pf.longest_tolerant_line(shallow), 150)
        wave = [int(30 + 12 * np.sin(i / 5.0)) for i in range(160)]
        self.assertLess(pf.longest_tolerant_line(wave), 40)

    def test_photo_window_rectangle_passes(self):
        rc, report = self.run_preflight(full_plan("photo_window"), rect_mask())
        self.assertEqual(rc, 0, report["errors"])

    def test_photo_window_nonrectangular_rejected(self):
        rc, report = self.run_preflight(full_plan("photo_window"), blob_mask())
        self.assertEqual(rc, 1)
        self.assertTrue(any("not rectangular" in e for e in report["errors"]),
                        report["errors"])

    def test_photo_echo_torn_seam_passes(self):
        rc, report = self.run_preflight(full_plan("photo_echo"),
                                        photo_echo_mask())
        self.assertEqual(rc, 0, report["errors"])
        echo = report["mask_metrics"]["photo_echo"]
        self.assertEqual(echo["seam_sides"], ["top"])
        self.assertGreaterEqual(echo["border_bleed_fraction"],
                                pf.BORDER_BLEED_MIN_FRACTION)

    def test_photo_echo_straight_seam_rejected(self):
        rc, report = self.run_preflight(full_plan("photo_echo"),
                                        photo_echo_mask(straight=True))
        self.assertEqual(rc, 1)
        self.assertTrue(any("seam" in e and "straight" in e
                            for e in report["errors"]), report["errors"])

    def test_photo_echo_floating_mask_rejected(self):
        rc, report = self.run_preflight(full_plan("photo_echo"), blob_mask())
        self.assertEqual(rc, 1)
        self.assertTrue(any("full-bleed" in e for e in report["errors"]),
                        report["errors"])

    def test_full_bleed_mask_rejected_in_organic_mode(self):
        # The border exemption exists ONLY in photo_echo; the same mask in
        # an organic mode must still fail on its straight border edges.
        rc, report = self.run_preflight(full_plan(), photo_echo_mask())
        self.assertEqual(rc, 1)
        self.assertTrue(report["errors"])

    def test_photo_echo_plan_requirements(self):
        plan = full_plan("photo_echo")
        del plan["seam"]
        plan["window"] = {}
        rc, report = self.run_preflight(plan, photo_echo_mask())
        self.assertEqual(rc, 1)
        self.assertTrue(any("window.type=torn_seam" in e
                            for e in report["errors"]), report["errors"])
        self.assertTrue(any("seam object" in e for e in report["errors"]),
                        report["errors"])
        # torn_seam window is exclusive to photo_echo.
        plan2 = full_plan()
        plan2["window"] = {"type": "torn_seam"}
        rc2, report2 = self.run_preflight(plan2, blob_mask())
        self.assertEqual(rc2, 1)
        self.assertTrue(any("only allowed with mode=photo_echo" in e
                            for e in report2["errors"]), report2["errors"])

    def test_antialiased_mask_warns(self):
        mask = rect_mask()
        arr = (mask * 255).astype(np.uint8)
        arr[100, 30:40] = 90  # gray, below the >127 binarization threshold
        with tempfile.TemporaryDirectory() as td:
            plan_path = os.path.join(td, "plan.json")
            mask_path = os.path.join(td, "mask.png")
            out_path = os.path.join(td, "report.json")
            with open(plan_path, "w", encoding="utf-8") as fh:
                json.dump(full_plan("photo_window"), fh)
            Image.fromarray(arr).save(mask_path)
            run_script("preflight_composition.py", "--plan", plan_path,
                       "--mask", mask_path, "--out", out_path)
            with open(out_path, "r", encoding="utf-8") as fh:
                report = json.load(fh)
        self.assertTrue(any("anti-aliased" in w for w in report["warnings"]),
                        report["warnings"])

    def test_source_overlay_preview(self):
        mask = blob_mask()
        with tempfile.TemporaryDirectory() as td:
            plan_path = os.path.join(td, "plan.json")
            mask_path = os.path.join(td, "mask.png")
            src_path = os.path.join(td, "src.png")
            out_path = os.path.join(td, "report.json")
            preview_path = os.path.join(td, "preview.png")
            with open(plan_path, "w", encoding="utf-8") as fh:
                json.dump(full_plan(), fh)
            save_mask(mask, mask_path)
            Image.new("RGB", (mask.shape[1], mask.shape[0]),
                      (200, 120, 40)).save(src_path)
            proc = run_script("preflight_composition.py", "--plan", plan_path,
                              "--mask", mask_path, "--out", out_path,
                              "--mask-preview", preview_path,
                              "--source", src_path)
            self.assertEqual(proc.returncode, 0, proc.stdout)
            preview = np.asarray(Image.open(preview_path).convert("RGB"))
        # Protected region shows full-brightness source, outside is dimmed.
        # The red bbox outline overlaps a few edge pixels, so sample the
        # interior and use a fraction for the bulk check.
        center = tuple(preview[110, 110])
        self.assertEqual(center, (200, 120, 40))
        full_frac = float(np.mean(preview[mask][:, 0] == 200))
        self.assertGreater(full_frac, 0.98)
        corner = tuple(preview[5, 5])
        self.assertEqual(corner, (60, 36, 12))  # 200,120,40 dimmed to 30%

    def test_sawtooth_regularity_unit(self):
        diffs = [3, 3, -3, -3] * 40
        seq = np.concatenate([[0], np.cumsum(diffs)]).tolist()
        period, frac = pf.sawtooth_regularity(seq)
        self.assertGreaterEqual(frac, 0.99)
        self.assertGreater(period, 0)


class RestoreTests(unittest.TestCase):

    def setup_files(self, td, placement=None, source_size=(4, 4)):
        placement = placement or {"x": 4, "y": 4, "width": 4, "height": 4}
        manifest = {"mode": "subject_cutout", "source": "src.png",
                    "alpha_policy": "nontransparent", "placement": placement}
        manifest_path = os.path.join(td, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)
        Image.new("RGBA", source_size, (255, 0, 0, 255)).save(
            os.path.join(td, "src.png"))
        base_path = os.path.join(td, "base.png")
        Image.new("RGBA", (16, 16), (0, 0, 0, 255)).save(base_path)
        return manifest_path, base_path

    def run_restore(self, td, manifest_path, base_path, extra=()):
        out = os.path.join(td, "final.png")
        report_path = os.path.join(td, "report.json")
        proc = run_script("restore_and_verify.py",
                          "--manifest", manifest_path, "--ai-base", base_path,
                          "--out", out, "--report", report_path, *extra)
        report = None
        if os.path.exists(report_path):
            with open(report_path, "r", encoding="utf-8") as fh:
                report = json.load(fh)
        return proc, report

    def test_roundtrip_verified(self):
        with tempfile.TemporaryDirectory() as td:
            manifest_path, base_path = self.setup_files(td)
            proc, report = self.run_restore(td, manifest_path, base_path)
        self.assertEqual(proc.returncode, 0, report)
        self.assertTrue(report["verified"])
        self.assertEqual(report["mismatched_pixel_count"], 0)
        self.assertEqual(report["sha256_expected"], report["sha256_actual"])
        self.assertIn("source_file_sha256", report)

    def test_float_placement_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            manifest_path, base_path = self.setup_files(
                td, placement={"x": 0.9, "y": 4, "width": 4, "height": 4})
            proc, report = self.run_restore(td, manifest_path, base_path)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(report["verified"])
        self.assertTrue(any("must all be integers" in e
                            for e in report["errors"]), report["errors"])

    def test_plan_cross_check_match(self):
        with tempfile.TemporaryDirectory() as td:
            manifest_path, base_path = self.setup_files(td)
            plan_path = os.path.join(td, "plan.json")
            with open(plan_path, "w", encoding="utf-8") as fh:
                json.dump(full_plan(), fh)
            proc, report = self.run_restore(td, manifest_path, base_path,
                                            extra=("--plan", plan_path))
        self.assertEqual(proc.returncode, 0, report)
        self.assertIn("plan_file_sha256", report)

    def test_plan_cross_check_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            manifest_path, base_path = self.setup_files(td)
            plan = full_plan(
                placement={"x": 9, "y": 4, "width": 4, "height": 4})
            plan_path = os.path.join(td, "plan.json")
            with open(plan_path, "w", encoding="utf-8") as fh:
                json.dump(plan, fh)
            proc, report = self.run_restore(td, manifest_path, base_path,
                                            extra=("--plan", plan_path))
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(any("plan cross-check" in e for e in report["errors"]),
                        report["errors"])

    def test_io_failure_still_writes_report(self):
        with tempfile.TemporaryDirectory() as td:
            manifest_path, _ = self.setup_files(td)
            missing_base = os.path.join(td, "missing.png")
            proc, report = self.run_restore(td, manifest_path, missing_base)
        self.assertEqual(proc.returncode, 2)
        self.assertIsNotNone(report, "exit-2 path must write the report")
        self.assertFalse(report["verified"])

    def test_provenance_fields(self):
        with tempfile.TemporaryDirectory() as td:
            manifest_path, base_path = self.setup_files(td)
            with open(manifest_path, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)
            Image.new("L", (4, 4), 255).save(os.path.join(td, "mask.png"))
            manifest["mask"] = "mask.png"
            manifest["generation_prompt"] = "paper field, no halos"
            with open(manifest_path, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh)
            plan = full_plan()
            plan["source_crop"] = {"x": 10, "y": 20, "width": 4, "height": 4}
            plan_path = os.path.join(td, "plan.json")
            with open(plan_path, "w", encoding="utf-8") as fh:
                json.dump(plan, fh)
            proc, report = self.run_restore(td, manifest_path, base_path,
                                            extra=("--plan", plan_path))
        self.assertEqual(proc.returncode, 0, report)
        self.assertIn("mask_file_sha256", report)
        self.assertEqual(report["mask_size"], [4, 4])
        self.assertEqual(report["source_size"], [4, 4])
        self.assertEqual(report["canvas_size"], [16, 16])
        self.assertIn("generation_prompt_sha256", report)
        self.assertEqual(report["plan_source_crop"]["x"], 10)

    def test_mask_size_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            manifest_path, base_path = self.setup_files(td)
            with open(manifest_path, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)
            Image.new("L", (5, 5), 255).save(os.path.join(td, "mask.png"))
            manifest["mask"] = "mask.png"
            with open(manifest_path, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh)
            proc, report = self.run_restore(td, manifest_path, base_path)
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(any("mask size" in e for e in report["errors"]),
                        report["errors"])


class VisualReviewTests(unittest.TestCase):

    def make_review(self, td, **overrides):
        Image.new("RGB", (64, 64), (10, 10, 10)).save(
            os.path.join(td, "final.png"))
        Image.new("RGB", (16, 16), (10, 10, 10)).save(
            os.path.join(td, "final.thumbnail.png"))
        review = {
            "review_image": "final.png",
            "thumbnail_image": "final.thumbnail.png",
            "rectangular_read": "pass",
            "sticker_border": "pass",
            "transition_blending": "pass",
            "edge_tactility": "pass",
            "shape_serves_motion": "pass",
            "no_default_oval_island": "pass",
            "micro_text_legible": "not_applicable",
            "review_notes": "transitions blend into the paper grain",
        }
        review.update(overrides)
        path = os.path.join(td, "final-visual-review.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(review, fh)
        return path

    def test_thumbnail_generation(self):
        with tempfile.TemporaryDirectory() as td:
            final = os.path.join(td, "final.png")
            thumb = os.path.join(td, "thumb.png")
            Image.new("RGB", (800, 600), (40, 80, 120)).save(final)
            proc = run_script("visual_review.py", "--final", final,
                              "--thumbnail", thumb, "--max-size", "256")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with Image.open(thumb) as img:
                size = img.size
        self.assertLessEqual(max(size), 256)

    def test_all_pass_review(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.make_review(td)
            proc = run_script("visual_review.py", "--check", path)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_fail_verdict_is_legal_and_exits_1(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.make_review(td, rectangular_read="fail")
            proc = run_script("visual_review.py", "--check", path)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Stage B", proc.stderr)

    def test_schema_violations_exit_2(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.make_review(td, transition_blending=True,
                                    review_notes="")
            proc = run_script("visual_review.py", "--check", path)
        self.assertEqual(proc.returncode, 2)

    def test_missing_evidence_image_exit_2(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.make_review(td, review_image="nope.png")
            proc = run_script("visual_review.py", "--check", path)
        self.assertEqual(proc.returncode, 2)


class RunnerTests(unittest.TestCase):

    def setup_inputs(self, td):
        plan_path = os.path.join(td, "plan.json")
        with open(plan_path, "w", encoding="utf-8") as fh:
            json.dump(full_plan(), fh)
        mask_path = os.path.join(td, "mask.png")
        save_mask(blob_mask(), mask_path)
        manifest_path = os.path.join(td, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump({"mode": "subject_cutout", "source": "src.png",
                       "alpha_policy": "nontransparent",
                       "placement": {"x": 4, "y": 4,
                                     "width": 4, "height": 4}}, fh)
        Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(
            os.path.join(td, "src.png"))
        base_path = os.path.join(td, "base.png")
        Image.new("RGBA", (16, 16), (0, 0, 0, 255)).save(base_path)
        return plan_path, mask_path, manifest_path, base_path

    def read_status(self, workdir):
        with open(os.path.join(workdir, "pipeline-status.json"),
                  "r", encoding="utf-8") as fh:
            return json.load(fh)

    def test_full_pipeline_passes(self):
        with tempfile.TemporaryDirectory() as td:
            plan, mask, manifest, base = self.setup_inputs(td)
            workdir = os.path.join(td, "out")
            proc = run_script("run_compositor.py", "--workdir", workdir,
                              "--plan", plan, "--mask", mask,
                              "--manifest", manifest, "--ai-base", base)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            status = self.read_status(workdir)
            self.assertTrue(status["ok"])
            done = {s["stage"]: s["ok"] for s in status["stages"]}
            self.assertTrue(done["preflight"])
            self.assertTrue(done["restore_and_verify"])
            self.assertTrue(done["thumbnail"])
            self.assertIsNone(done["visual_review"])  # pending, not run
            for name in ("composition.preflight.json", "final.png",
                         "final.verification.json", "final.thumbnail.png"):
                self.assertTrue(os.path.exists(os.path.join(workdir, name)),
                                name)

    def test_generation_state_is_carried_into_pipeline_status(self):
        with tempfile.TemporaryDirectory() as td:
            plan, mask, manifest, base = self.setup_inputs(td)
            workdir = os.path.join(td, "out")
            state = os.path.join(td, "generation-state.json")
            with open(state, "w", encoding="utf-8") as fh:
                json.dump({"status": "fallback_accepted",
                           "stage_b_ai": "rejected"}, fh)
            proc = run_script("run_compositor.py", "--workdir", workdir,
                              "--plan", plan, "--mask", mask,
                              "--manifest", manifest, "--ai-base", base,
                              "--generation-state", state)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            status = self.read_status(workdir)
            self.assertEqual(status["generation"]["status"],
                             "fallback_accepted")

    def test_failed_visual_review_fails_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            plan, mask, manifest, base = self.setup_inputs(td)
            workdir = os.path.join(td, "out")
            review_path = os.path.join(workdir, "final-visual-review.json")
            os.makedirs(workdir)
            with open(review_path, "w", encoding="utf-8") as fh:
                json.dump({"review_image": "final.png",
                           "thumbnail_image": "final.thumbnail.png",
                           "rectangular_read": "fail",
                           "sticker_border": "pass",
                           "transition_blending": "pass",
                           "edge_tactility": "pass",
                           "shape_serves_motion": "pass",
                           "no_default_oval_island": "pass",
                           "micro_text_legible": "not_applicable",
                           "review_notes": "still reads as a rectangle"}, fh)
            proc = run_script("run_compositor.py", "--workdir", workdir,
                              "--plan", plan, "--mask", mask,
                              "--manifest", manifest, "--ai-base", base,
                              "--review", review_path)
            self.assertEqual(proc.returncode, 1)
            status = self.read_status(workdir)
            self.assertFalse(status["ok"])
            done = {s["stage"]: s["ok"] for s in status["stages"]}
            self.assertFalse(done["visual_review"])

    def test_preflight_failure_stops_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            plan, _, manifest, base = self.setup_inputs(td)
            bad_mask = os.path.join(td, "rect.png")
            save_mask(rect_mask(), bad_mask)
            workdir = os.path.join(td, "out")
            proc = run_script("run_compositor.py", "--workdir", workdir,
                              "--plan", plan, "--mask", bad_mask,
                              "--manifest", manifest, "--ai-base", base)
            self.assertEqual(proc.returncode, 1)
            status = self.read_status(workdir)
            stages = [s["stage"] for s in status["stages"]]
            self.assertEqual(stages, ["preflight"])
            self.assertFalse(os.path.exists(
                os.path.join(workdir, "final.png")))


class SmoothMaskTests(unittest.TestCase):

    def test_polygon_chaikin_cuts_corners(self):
        with tempfile.TemporaryDirectory() as td:
            poly_path = os.path.join(td, "points.json")
            out_path = os.path.join(td, "mask.png")
            with open(poly_path, "w", encoding="utf-8") as fh:
                json.dump([[40, 40], [180, 40], [180, 180], [40, 180]], fh)
            proc = run_script("smooth_mask.py", "--polygon", poly_path,
                              "--canvas", "220x220", "--out", out_path,
                              "--iterations", "4")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            arr = np.asarray(Image.open(out_path).convert("L"))
        self.assertTrue(set(np.unique(arr)) <= {0, 255})
        mask = arr > 127
        metrics = pf.analyze_mask(mask)
        # Corner cutting must leave the shape less than fully rectangular.
        self.assertLess(metrics["rectangularity"], 0.98)
        self.assertGreater(int(mask.sum()), 0)

    def test_blur_smoothing_removes_sawtooth(self):
        rough = sawtooth_mask()
        self.assertGreaterEqual(
            pf.analyze_mask(rough)["sawtooth"]["match_fraction"], 0.9)
        with tempfile.TemporaryDirectory() as td:
            in_path = os.path.join(td, "rough.png")
            out_path = os.path.join(td, "smooth.png")
            save_mask(rough, in_path)
            proc = run_script("smooth_mask.py", "--mask", in_path,
                              "--out", out_path, "--blur-radius", "6",
                              "--passes", "2")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            arr = np.asarray(Image.open(out_path).convert("L"))
        self.assertTrue(set(np.unique(arr)) <= {0, 255})
        smoothed = pf.analyze_mask(arr > 127)
        self.assertLess(smoothed["sawtooth"]["match_fraction"], 0.9)

    def test_chaikin_point_count(self):
        pts = sm.chaikin([(0, 0), (10, 0), (10, 10)], 2)
        self.assertEqual(len(pts), 12)


class GenerationGuardTests(unittest.TestCase):

    def test_generation_output_normalization(self):
        with tempfile.TemporaryDirectory() as td:
            source = os.path.join(td, "source.png")
            out = os.path.join(td, "normalized.png")
            Image.new("RGB", (11, 7), (240, 230, 210)).save(source)
            proc = run_script("normalize_generation_output.py", "--input",
                              source, "--expected-size", "16x16", "--out", out)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with Image.open(out) as image:
                self.assertEqual(image.size, (16, 16))

    def test_generation_output_identity_is_not_resized(self):
        with tempfile.TemporaryDirectory() as td:
            source = os.path.join(td, "source.png")
            out = os.path.join(td, "normalized.png")
            Image.new("RGBA", (16, 16), (240, 230, 210, 255)).save(source)
            proc = run_script("normalize_generation_output.py", "--input",
                              source, "--expected-size", "16x16", "--out", out)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with Image.open(out) as image:
                self.assertEqual(image.mode, "RGBA")

    def test_environment_preflight_does_not_expose_credential(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "environment.json")
            env = os.environ.copy()
            env.pop("TEST_IMAGE_KEY", None)
            proc = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS,
                 "preflight_environment.py"), "--out", out,
                 "--final-size", "1242x1660", "--credential-env",
                 "TEST_IMAGE_KEY"], capture_output=True, text=True, env=env)
            self.assertEqual(proc.returncode, 1)
            with open(out, encoding="utf-8") as fh:
                report = json.load(fh)
            self.assertFalse(report["verified"])
            self.assertNotIn("secret", proc.stdout.lower())

    def test_environment_preflight_records_deterministic_crop(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "environment.json")
            env = os.environ.copy(); env["TEST_IMAGE_KEY"] = "present"
            proc = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS,
                 "preflight_environment.py"), "--out", out,
                 "--final-size", "1242x1660", "--generation-size",
                 "1248x1664", "--credential-env", "TEST_IMAGE_KEY"],
                capture_output=True, text=True, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with open(out, encoding="utf-8") as fh:
                report = json.load(fh)
            self.assertTrue(any("differs" in w for w in report["warnings"]))

    def test_transition_mask_never_marks_protected_pixels_editable(self):
        with tempfile.TemporaryDirectory() as td:
            mask = os.path.join(td, "mask.png")
            out = os.path.join(td, "transition.png")
            save_mask(blob_mask(40, 10), mask)
            proc = run_script("build_transition_mask.py", "--mask", mask,
                              "--canvas", "80x80", "--placement", "20,20",
                              "--out", out)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            alpha = np.asarray(Image.open(out).getchannel("A"))
            local = alpha[20:60, 20:60]
            protected = np.asarray(Image.open(mask).convert("L")) > 127
            self.assertTrue(np.all(local[protected] == 255))
            self.assertGreater(int((local == 0).sum()), 0)

    def test_stage_b_preflight_rejects_size_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            image = os.path.join(td, "image.png")
            edit = os.path.join(td, "edit.png")
            protected = os.path.join(td, "protected.png")
            out = os.path.join(td, "report.json")
            Image.new("RGBA", (32, 32), (240, 230, 210, 255)).save(image)
            Image.new("RGBA", (31, 32), (255, 255, 255, 255)).save(edit)
            save_mask(blob_mask(8, 2), protected)
            proc = run_script("preflight_stage_b.py", "--image", image,
                              "--edit-mask", edit, "--protected-mask", protected,
                              "--placement", "10,10", "--out", out)
            self.assertEqual(proc.returncode, 1)
            with open(out, encoding="utf-8") as fh:
                report = json.load(fh)
            self.assertTrue(any("size mismatch" in e for e in report["errors"]))

    def test_generation_gate_blocks_exhausted_stage_a(self):
        with tempfile.TemporaryDirectory() as td:
            state = os.path.join(td, "state.json")
            out = os.path.join(td, "gate.json")
            with open(state, "w", encoding="utf-8") as fh:
                json.dump({"stage_a_attempts_used": 1,
                           "stage_a_max_attempts": 1}, fh)
            proc = run_script("generation_gate.py", "--state", state,
                              "--stage", "stage-a", "--out", out)
            self.assertEqual(proc.returncode, 1)
            with open(out, encoding="utf-8") as fh:
                report = json.load(fh)
            self.assertFalse(report["allowed"])

    def test_generation_cache_record_then_lookup(self):
        with tempfile.TemporaryDirectory() as td:
            source = os.path.join(td, "source.png")
            plan = os.path.join(td, "plan.json")
            prompt = os.path.join(td, "prompt.txt")
            artifact = os.path.join(td, "artifact.png")
            cache = os.path.join(td, "cache")
            Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(source)
            with open(plan, "w", encoding="utf-8") as fh: fh.write("{}")
            with open(prompt, "w", encoding="utf-8") as fh: fh.write("paper")
            Image.new("RGBA", (16, 16), (4, 5, 6, 255)).save(artifact)
            common = ("--stage", "stage-a", "--source", source, "--plan", plan,
                      "--prompt", prompt, "--model", "test-model",
                      "--canvas", "16x16", "--cache-dir", cache)
            rec = run_script("cache_generation.py", "record", *common,
                             "--artifact", artifact)
            self.assertEqual(rec.returncode, 0, rec.stderr)
            lookup = run_script("cache_generation.py", "lookup", *common)
            self.assertEqual(lookup.returncode, 0, lookup.stderr)
            self.assertTrue(json.loads(lookup.stdout)["cache_hit"])


if __name__ == "__main__":
    unittest.main()
