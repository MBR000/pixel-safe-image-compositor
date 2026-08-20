#!/usr/bin/env python3
"""Validate a Stage B image/edit-mask request before provider submission."""

import argparse
import json
import sys

import numpy as np
from PIL import Image


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--image", required=True)
    p.add_argument("--edit-mask", required=True)
    p.add_argument("--protected-mask", required=True,
                   help="local binary protected mask")
    p.add_argument("--placement", required=True, help="x,y offset")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    errors = []
    try:
        image = Image.open(args.image).convert("RGBA")
        edit = Image.open(args.edit_mask).convert("RGBA")
        protected = np.asarray(Image.open(args.protected_mask).convert("L")) > 127
        ox, oy = (int(v) for v in args.placement.split(","))
    except (OSError, ValueError) as exc:
        errors.append("cannot read Stage B inputs: %s" % exc)
        image = edit = None; protected = np.zeros((0, 0), dtype=bool); ox = oy = 0
    if image is not None:
        if image.size != edit.size:
            errors.append("image/edit-mask size mismatch: %s vs %s" %
                          (image.size, edit.size))
        if len(np.unique(np.asarray(edit.getchannel("A")))) > 2:
            errors.append("edit mask alpha must be binary 0/255")
        alpha = np.asarray(edit.getchannel("A"))
        h, w = protected.shape
        if ox < 0 or oy < 0 or oy + h > edit.height or ox + w > edit.width:
            errors.append("protected placement exceeds Stage B image")
        elif np.any(alpha[oy:oy + h, ox:ox + w][protected] != 255):
            errors.append("protected pixels are editable in Stage B mask")
        editable = int((alpha == 0).sum())
    else:
        editable = 0
    report = {"verified": not errors, "errors": errors,
              "image_size": list(image.size) if image else None,
              "edit_mask_size": list(edit.size) if edit else None,
              "editable_pixels": editable, "placement": [ox, oy]}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2); fh.write("\n")
    print(json.dumps(report, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
