#!/usr/bin/env python3
"""Evidence-based visual review for pixel-safe-image-compositor.

The plan's `preview_review_requirements` are pre-generation commitments.
This script handles the post-generation side:

1. Thumbnail mode: render the evidence thumbnail the reviewer must look at.

       python visual_review.py --final final.png \
           --thumbnail final.thumbnail.png [--max-size 256]

2. Check mode: validate a filled final-visual-review.json. Unlike the
   preflight checklist, "fail" is a legal verdict here - the point is an
   honest record, not a rubber stamp. Any "fail" exits 1 with instructions
   to regenerate ONLY the Stage B transition layer (the protected subject
   is already verified and must not be regenerated).

       python visual_review.py --check final-visual-review.json

Required review fields:
    review_image, thumbnail_image (paths relative to the review file),
    rectangular_read, sticker_border, transition_blending,
    edge_tactility ("pass"/"fail"),
    micro_text_legible ("pass"/"fail"/"not_applicable"),
    shape_serves_motion, no_default_oval_island ("pass"/"fail"),
    review_notes (non-empty string).

edge_tactility asks: does the boundary read as a tactile paper edge (torn
fiber, fringe) rather than a clean digital cutout? micro_text_legible asks:
is the planned micro-text correctly spelled and legible ("not_applicable"
when the plan set micro_text to null).

Exit codes: 0 = all pass, 1 = at least one fail verdict,
2 = usage/IO/schema error.
"""

import argparse
import json
import os
import sys

from PIL import Image

VERDICT_FIELDS = ("rectangular_read", "sticker_border",
                  "transition_blending", "edge_tactility",
                  "shape_serves_motion", "no_default_oval_island")
TRI_VERDICT_FIELDS = ("micro_text_legible",)
REQUIRED_FIELDS = ("review_image", "thumbnail_image", "review_notes") \
    + VERDICT_FIELDS + TRI_VERDICT_FIELDS


def make_thumbnail(final_path, thumbnail_path, max_size):
    img = Image.open(final_path)
    img.thumbnail((max_size, max_size))
    img.save(thumbnail_path, "PNG")
    return img.size


def check_review(review_path):
    """Returns (exit_code, summary_dict)."""
    schema_errors = []
    try:
        with open(review_path, "r", encoding="utf-8") as fh:
            review = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return 2, {"ok": False, "errors": ["cannot read review: %s" % exc]}

    for f in REQUIRED_FIELDS:
        if f not in review:
            schema_errors.append("missing field: %s" % f)
    for f in VERDICT_FIELDS:
        if f in review and review[f] not in ("pass", "fail"):
            schema_errors.append(
                "%s must be 'pass' or 'fail', got %r" % (f, review[f]))
    for f in TRI_VERDICT_FIELDS:
        if f in review and review[f] not in ("pass", "fail",
                                             "not_applicable"):
            schema_errors.append(
                "%s must be 'pass', 'fail', or 'not_applicable', got %r"
                % (f, review[f]))
    notes = review.get("review_notes")
    if "review_notes" in review and (
            not isinstance(notes, str) or not notes.strip()):
        schema_errors.append("review_notes must be a non-empty string")

    base_dir = os.path.dirname(os.path.abspath(review_path))
    for f in ("review_image", "thumbnail_image"):
        path = review.get(f)
        if isinstance(path, str) and path:
            if not os.path.exists(os.path.join(base_dir, path)):
                schema_errors.append(
                    "%s does not exist: %s (the review must reference real "
                    "evidence images)" % (f, path))

    if schema_errors:
        return 2, {"ok": False, "errors": schema_errors}

    all_verdicts = VERDICT_FIELDS + TRI_VERDICT_FIELDS
    failed = [f for f in all_verdicts if review[f] == "fail"]
    summary = {
        "ok": not failed,
        "verdicts": {f: review[f] for f in all_verdicts},
        "failed": failed,
        "review_notes": review["review_notes"],
    }
    return (1 if failed else 0), summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--final", help="final.png to thumbnail")
    parser.add_argument("--thumbnail", help="thumbnail output path")
    parser.add_argument("--max-size", type=int, default=256,
                        help="thumbnail max dimension (default 256)")
    parser.add_argument("--check", help="final-visual-review.json to validate")
    args = parser.parse_args()

    if args.final or args.thumbnail:
        if not (args.final and args.thumbnail):
            print("--final and --thumbnail must be used together",
                  file=sys.stderr)
            return 2
        try:
            size = make_thumbnail(args.final, args.thumbnail, args.max_size)
        except OSError as exc:
            print("cannot create thumbnail: %s" % exc, file=sys.stderr)
            return 2
        print(json.dumps({"thumbnail": args.thumbnail,
                          "size": list(size)}, indent=2))
        if not args.check:
            return 0

    if args.check:
        code, summary = check_review(args.check)
        print(json.dumps(summary, indent=2))
        if code == 1:
            print("visual review FAILED on: %s. Regenerate ONLY the Stage B "
                  "transition layer and re-run restore_and_verify; do NOT "
                  "regenerate the verified protected subject."
                  % ", ".join(summary["failed"]), file=sys.stderr)
        return code

    if not (args.final or args.check):
        print("nothing to do: pass --final/--thumbnail and/or --check",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
