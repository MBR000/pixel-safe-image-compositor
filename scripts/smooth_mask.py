#!/usr/bin/env python3
"""Smooth a protected-region mask for pixel-safe-image-compositor.

Two input forms:

1. Polygon mode: read a JSON list of [x, y] points describing a closed
   outline, apply Chaikin corner cutting, and rasterize the smoothed curve
   to a binary mask PNG.
2. Mask mode: read an existing mask PNG, apply Gaussian blur passes, and
   re-binarize at >127 to round off corners and regular sawtooth.

Usage:
    python smooth_mask.py --polygon points.json --canvas 1024x1024 \
        --out mask.png [--iterations 3]
    python smooth_mask.py --mask rough-mask.png --out mask.png \
        [--blur-radius 6] [--passes 2]

Always re-run preflight_composition.py on the smoothed mask: smoothing
helps meet the geometry limits but does not guarantee them.

Exit codes: 0 = ok, 2 = usage/IO error.
"""

import argparse
import json
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def chaikin(points, iterations):
    """Chaikin corner cutting on a closed polygon."""
    pts = [(float(x), float(y)) for x, y in points]
    for _ in range(iterations):
        cut = []
        n = len(pts)
        for i in range(n):
            (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
            cut.append((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1))
            cut.append((0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))
        pts = cut
    return pts


def binarize(img):
    return ((np.asarray(img.convert("L")) > 127) * 255).astype(np.uint8)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--polygon", help="JSON file with a list of [x, y] "
                                         "points (closed outline)")
    group.add_argument("--mask", help="existing mask PNG to smooth")
    parser.add_argument("--out", required=True, help="output mask PNG path")
    parser.add_argument("--canvas", default=None,
                        help="canvas size WxH (required with --polygon)")
    parser.add_argument("--iterations", type=int, default=3,
                        help="Chaikin iterations for --polygon (default 3)")
    parser.add_argument("--blur-radius", type=float, default=6.0,
                        help="Gaussian blur radius for --mask (default 6)")
    parser.add_argument("--passes", type=int, default=2,
                        help="blur+rebinarize passes for --mask (default 2)")
    args = parser.parse_args()

    if args.polygon:
        if not args.canvas:
            print("--canvas WxH is required with --polygon", file=sys.stderr)
            return 2
        try:
            width, height = (int(v) for v in args.canvas.lower().split("x"))
            with open(args.polygon, "r", encoding="utf-8") as fh:
                points = json.load(fh)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print("cannot read polygon input: %s" % exc, file=sys.stderr)
            return 2
        if not isinstance(points, list) or len(points) < 3:
            print("polygon must be a JSON list of at least 3 [x, y] points",
                  file=sys.stderr)
            return 2
        smoothed = chaikin(points, max(args.iterations, 0))
        img = Image.new("L", (width, height), 0)
        ImageDraw.Draw(img).polygon(smoothed, fill=255)
        arr = binarize(img)
    else:
        try:
            img = Image.open(args.mask).convert("L")
        except OSError as exc:
            print("cannot read mask: %s" % exc, file=sys.stderr)
            return 2
        arr = binarize(img)
        for _ in range(max(args.passes, 1)):
            blurred = Image.fromarray(arr).filter(
                ImageFilter.GaussianBlur(args.blur_radius))
            arr = binarize(blurred)

    Image.fromarray(arr).save(args.out, "PNG")
    summary = {
        "out": args.out,
        "area_px": int((arr > 127).sum()),
        "size": [arr.shape[1], arr.shape[0]],
    }
    print(json.dumps(summary, indent=2))
    if not summary["area_px"]:
        print("smoothed mask is empty", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
