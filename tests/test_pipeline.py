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
    return {
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
        "preview_review": {k: True for k in pf.REQUIRED_REVIEW_FIELDS},
    }


def blob_mask(size=220, radius=70):
    """Smooth free-form blob that satisfies all organic geometry limits."""
    yy, xx = np.mgrid[0:size, 0:size].astype(float)
    cy = cx = size / 2.0
    ang = np.arctan2(yy - cy, xx - cx)
    rad = np.hypot(yy - cy, xx - cx)
    wobble = (1.0 + 0.22 * np.sin(3 * ang + 0.7)
              + 0.11 * np.sin(7 * ang + 1.9)
              + 0.06 * np.sin(13 * ang + 4.2))
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
        plan["preview_review"] = {k: False
                                  for k in pf.REQUIRED_REVIEW_FIELDS}
        plan["edge_profile"]["variation_scales"]["medium"] = False
        rc, report = self.run_preflight(plan, blob_mask())
        self.assertEqual(rc, 1)
        self.assertTrue(
            any("variation_scales.medium must be true" in e
                for e in report["errors"]), report["errors"])
        review_errors = [e for e in report["errors"]
                         if e.startswith("preview_review.")]
        self.assertEqual(len(review_errors), len(pf.REQUIRED_REVIEW_FIELDS))

    def test_photo_window_rectangle_passes(self):
        rc, report = self.run_preflight(full_plan("photo_window"), rect_mask())
        self.assertEqual(rc, 0, report["errors"])

    def test_photo_window_nonrectangular_rejected(self):
        rc, report = self.run_preflight(full_plan("photo_window"), blob_mask())
        self.assertEqual(rc, 1)
        self.assertTrue(any("not rectangular" in e for e in report["errors"]),
                        report["errors"])

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


if __name__ == "__main__":
    unittest.main()
