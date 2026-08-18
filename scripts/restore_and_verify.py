#!/usr/bin/env python3
"""Restore protected source pixels onto an AI base and verify them.

Only non-transparent pixels of the RGBA source are pasted back, at an integer
offset with no scaling, rotation, or perspective transform. The final PNG is
re-read from disk and the protected pixels are compared with SHA-256. Any
mismatch yields verified=false and a non-zero exit code.

Usage:
    python restore_and_verify.py \
        --ai-base final_ai_base.png \
        --manifest manifest.json \
        --out final.png \
        --report final.verification.json

Manifest (paths are relative to the manifest file):
{
  "mode": "subject_cutout",
  "source": "./source_cutout.png",
  "placement": {"x": 120, "y": 80, "width": 640, "height": 640},
  "alpha_policy": "nontransparent"
}

Exit codes: 0 = verified, 1 = validation error or pixel mismatch,
2 = usage/IO error.
"""

import argparse
import hashlib
import json
import os
import sys

import numpy as np
from PIL import Image

FORBIDDEN_TRANSFORM_KEYS = (
    "scale", "rotate", "rotation", "perspective", "warp", "skew", "flip",
)


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def sha256_of_pixels(arr_rgba, mask):
    """SHA-256 over the RGBA bytes of the masked pixels, row-major."""
    return hashlib.sha256(arr_rgba[mask].tobytes()).hexdigest()


def sha256_of_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def usage_failure(args, message):
    """Report a usage/IO failure (exit 2) so callers never read a stale report."""
    print(message, file=sys.stderr)
    try:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump({"verified": False, "errors": [message]}, fh, indent=2)
            fh.write("\n")
    except OSError:
        pass
    return 2


def cross_check_plan(plan, manifest, errors):
    """Verify the manifest executes the preflight-approved plan."""
    plan_placement = plan.get("placement")
    if not isinstance(plan_placement, dict):
        errors.append("plan cross-check: plan.placement must be an object "
                      "with x, y, width, height")
        return
    manifest_placement = manifest.get("placement") or {}
    for key in ("x", "y", "width", "height"):
        if plan_placement.get(key) != manifest_placement.get(key):
            errors.append(
                "plan cross-check: placement.%s mismatch (plan=%r, "
                "manifest=%r); the manifest must execute the approved plan"
                % (key, plan_placement.get(key), manifest_placement.get(key)))
    plan_mode = plan.get("mode")
    manifest_mode = manifest.get("mode")
    if manifest_mode is not None and plan_mode != manifest_mode:
        errors.append("plan cross-check: mode mismatch (plan=%r, manifest=%r)"
                      % (plan_mode, manifest_mode))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ai-base", required=True,
                        help="AI-generated base image (stage A + B output)")
    parser.add_argument("--manifest", required=True, help="manifest JSON path")
    parser.add_argument("--out", required=True, help="final PNG output path")
    parser.add_argument("--report", required=True, help="verification JSON path")
    parser.add_argument("--plan", default=None,
                        help="optional composition-plan.json; when given, the "
                             "manifest placement and mode must match the plan")
    args = parser.parse_args()

    errors = []

    try:
        manifest = load_json(args.manifest)
    except (OSError, json.JSONDecodeError) as exc:
        return usage_failure(args, "cannot read manifest: %s" % exc)

    plan = None
    if args.plan:
        try:
            plan = load_json(args.plan)
        except (OSError, json.JSONDecodeError) as exc:
            return usage_failure(args, "cannot read plan: %s" % exc)
        cross_check_plan(plan, manifest, errors)

    for key in FORBIDDEN_TRANSFORM_KEYS:
        if key in manifest or key in (manifest.get("placement") or {}):
            errors.append(
                "forbidden transform %r: the protected region must not be "
                "scaled, rotated, or warped" % key)

    if manifest.get("alpha_policy") != "nontransparent":
        errors.append("alpha_policy must be 'nontransparent', got %r"
                      % manifest.get("alpha_policy"))

    placement = manifest.get("placement") or {}
    placement_values = [placement.get(k) for k in ("x", "y", "width", "height")]
    # bool is an int subclass, and int() silently truncates floats/parses
    # strings, so require exact int type instead of coercing.
    if all(type(v) is int for v in placement_values):
        px, py, pw, ph = placement_values
    else:
        errors.append(
            "placement x, y, width, height must all be integers (no floats, "
            "strings, or booleans), got %r" % (placement,))
        px = py = pw = ph = 0

    base_dir = os.path.dirname(os.path.abspath(args.manifest))
    source_path = manifest.get("source")
    if not source_path:
        errors.append("manifest missing 'source'")

    if errors:
        return finish(args, None, errors)

    source_abs = os.path.join(base_dir, source_path)
    try:
        src = Image.open(source_abs).convert("RGBA")
        base = Image.open(args.ai_base).convert("RGBA")
    except OSError as exc:
        return usage_failure(args, "cannot read image: %s" % exc)

    sw, sh = src.size
    if (pw, ph) != (sw, sh):
        errors.append(
            "placement size %dx%d differs from source size %dx%d; "
            "scaling the protected region is forbidden" % (pw, ph, sw, sh))
    bw, bh = base.size
    if px < 0 or py < 0 or px + pw > bw or py + ph > bh:
        errors.append(
            "placement (%d, %d, %d, %d) exceeds base canvas %dx%d"
            % (px, py, pw, ph, bw, bh))

    if errors:
        return finish(args, None, errors)

    src_arr = np.asarray(src)
    base_arr = np.asarray(base).copy()
    mask = src_arr[..., 3] > 0
    if not mask.any():
        errors.append("source has no non-transparent pixels")
        return finish(args, None, errors)

    # Programmatic restore: paste back ONLY the non-transparent source pixels.
    region = base_arr[py:py + ph, px:px + pw]
    region[mask] = src_arr[mask]

    Image.fromarray(base_arr).save(args.out, "PNG")

    # Re-read the written PNG and verify protected pixels with SHA-256.
    final_arr = np.asarray(Image.open(args.out).convert("RGBA"))
    final_region = final_arr[py:py + ph, px:px + pw]

    expected = sha256_of_pixels(src_arr, mask)
    actual = sha256_of_pixels(final_region, mask)
    mismatched = int(np.any(final_region[mask] != src_arr[mask], axis=1).sum())

    if expected != actual:
        errors.append("SHA-256 mismatch on protected pixels")

    result = {
        "verified": not errors,
        "alpha_policy": "nontransparent",
        "placement": {"x": px, "y": py, "width": pw, "height": ph},
        "protected_pixel_count": int(mask.sum()),
        "mismatched_pixel_count": mismatched,
        "sha256_expected": expected,
        "sha256_actual": actual,
        "source_file_sha256": sha256_of_file(source_abs),
        "errors": errors,
    }
    if args.plan:
        result["plan_file_sha256"] = sha256_of_file(args.plan)
    return finish(args, result, errors)


def finish(args, result, errors):
    if result is None:
        result = {"verified": False, "errors": errors}
    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
        fh.write("\n")
    print(json.dumps(result, indent=2))
    return 0 if result.get("verified") else 1


if __name__ == "__main__":
    sys.exit(main())
