#!/usr/bin/env python3
"""Build a sparse exterior-only edit mask for Stage B.

The output is RGBA: alpha 0 marks editable pixels and alpha 255 protects the
rest of the canvas. The editable area is a disconnected ring subset, never
the protected subject itself, so a model cannot repaint the full background.
"""

import argparse
import json
import sys

import numpy as np
from PIL import Image, ImageFilter


def parse_size(value):
    try:
        w, h = (int(v) for v in value.lower().split("x"))
        return w, h
    except (AttributeError, ValueError):
        raise argparse.ArgumentTypeError("size must be WxH")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--mask", required=True, help="local protected mask PNG")
    p.add_argument("--canvas", required=True, type=parse_size)
    p.add_argument("--placement", required=True, help="x,y offset")
    p.add_argument("--final-crop-offset", default="0,0",
                   help="generation-to-final crop x,y; added to placement")
    p.add_argument("--out", required=True)
    p.add_argument("--radius", type=int, default=30)
    args = p.parse_args()
    try:
        ox, oy = (int(v) for v in args.placement.split(","))
        crop_x, crop_y = (int(v) for v in args.final_crop_offset.split(","))
        ox += crop_x
        oy += crop_y
        local = np.asarray(Image.open(args.mask).convert("L")) > 127
    except (OSError, ValueError) as exc:
        print("cannot read mask/placement: %s" % exc, file=sys.stderr)
        return 2
    cw, ch = args.canvas
    if oy < 0 or ox < 0 or oy + local.shape[0] > ch or ox + local.shape[1] > cw:
        print("placement exceeds canvas", file=sys.stderr); return 1
    dil = np.asarray(Image.fromarray((local * 255).astype("uint8"))
                    .filter(ImageFilter.MaxFilter(max(3, args.radius * 2 + 1)))) > 127
    # Use three disconnected sectors to avoid a continuous halo around the edge.
    yy, xx = np.indices(local.shape)
    sectors = (((xx < local.shape[1] * 0.42) & (yy < local.shape[0] * 0.55)) |
               ((xx > local.shape[1] * 0.58) & (yy < local.shape[0] * 0.62)) |
               (yy > local.shape[0] * 0.60))
    editable = (dil & ~local & sectors)
    rgba = np.full((ch, cw, 4), 255, dtype=np.uint8)
    rgba[oy:oy + local.shape[0], ox:ox + local.shape[1], 3][editable] = 0
    Image.fromarray(rgba).save(args.out, "PNG")
    report = {"verified": bool(editable.any()), "canvas": [cw, ch],
              "editable_pixels": int(editable.sum()), "radius": args.radius,
              "generation_placement": [ox, oy],
              "final_crop_offset": [crop_x, crop_y],
              "semantics": "openai-transparent-editable"}
    print(json.dumps(report, indent=2))
    return 0 if editable.any() else 1


if __name__ == "__main__":
    sys.exit(main())
