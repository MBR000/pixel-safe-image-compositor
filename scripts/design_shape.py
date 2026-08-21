#!/usr/bin/env python3
"""Design an organic boundary shape BEFORE placing the subject.

Shape-first workflow: the boundary is a design element chosen from the
composition style (leaf, pebble, torn paper, brush blob) and the subject
is scaled and moved afterwards to fit it (fit_subject.py). Shapes are a
polar radius curve with three octaves of random harmonic variation -
large, medium, small - which is exactly what the organic geometry gates
expect from a hand-drawn edge.

Usage:
    python design_shape.py --template leaf --canvas 900x1100 \
        --out shape.png [--seed 7] [--fill 0.84] [--rotate 0]

Always run preflight_composition.py on the result: the randomness helps
meet the geometry limits but does not guarantee them; on a failure try
another seed.

Exit codes: 0 = ok, 2 = usage error.
"""

import argparse
import json
import sys

import numpy as np
from PIL import Image, ImageDraw

# axis: vertical elongation; tip: pointedness at the top end;
# amps: harmonic variation amplitude per octave (large, medium, small).
TEMPLATES = {
    "leaf":   {"axis": 1.55, "tip": 0.30, "amps": (0.10, 0.045, 0.018)},
    "pebble": {"axis": 1.15, "tip": 0.00, "amps": (0.09, 0.040, 0.015)},
    "torn":   {"axis": 1.25, "tip": 0.00, "amps": (0.16, 0.070, 0.030)},
    "brush":  {"axis": 2.10, "tip": 0.18, "amps": (0.12, 0.050, 0.020)},
}
# cycles-around-the-contour range per octave
OCTAVE_CYCLES = ((2, 4), (5, 10), (13, 24))


def parse_size(value):
    try:
        w, h = (int(v) for v in value.lower().split("x"))
        return w, h
    except (AttributeError, ValueError):
        raise argparse.ArgumentTypeError("size must be WxH")


def contour(template, rng, points):
    """Unit-scale polar contour (x, y arrays) for a template."""
    spec = TEMPLATES[template]
    theta = np.linspace(0.0, 2.0 * np.pi, points, endpoint=False)
    # ellipse radius with vertical semi-axis = axis, horizontal = 1
    r = 1.0 / np.sqrt(np.cos(theta) ** 2 + (np.sin(theta) / spec["axis"]) ** 2)
    r *= 1.0 + spec["tip"] * np.sin(theta)
    # three octaves, two random harmonics each: no periodic sawtooth,
    # variation at large, medium, and small scale
    for amp, (klo, khi) in zip(spec["amps"], OCTAVE_CYCLES):
        for _ in range(2):
            k = rng.integers(klo, khi + 1)
            phase = rng.uniform(0.0, 2.0 * np.pi)
            r *= 1.0 + amp * np.cos(k * theta + phase) / 2.0
    return r * np.cos(theta), r * np.sin(theta)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--template", required=True, choices=sorted(TEMPLATES))
    parser.add_argument("--canvas", required=True, type=parse_size)
    parser.add_argument("--out", required=True, help="output mask PNG path")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--fill", type=float, default=0.84,
                        help="shape extent as a fraction of the canvas "
                             "(default 0.84, leaves a quiet buffer)")
    parser.add_argument("--rotate", type=float, default=0.0,
                        help="rotation in degrees, counter-clockwise")
    parser.add_argument("--points", type=int, default=1440,
                        help="contour sampling density (default 1440)")
    args = parser.parse_args()

    if not 0.1 <= args.fill <= 0.98:
        print("--fill must be in [0.1, 0.98]", file=sys.stderr)
        return 2

    rng = np.random.default_rng(args.seed)
    x, y = contour(args.template, rng, max(args.points, 360))
    if args.rotate:
        a = np.deg2rad(args.rotate)
        x, y = x * np.cos(a) - y * np.sin(a), x * np.sin(a) + y * np.cos(a)

    w, h = args.canvas
    scale = min(w * args.fill / (x.max() - x.min()),
                h * args.fill / (y.max() - y.min()))
    cx = w / 2.0 - scale * (x.max() + x.min()) / 2.0
    cy = h / 2.0 - scale * (y.max() + y.min()) / 2.0
    poly = list(zip(scale * x + cx, scale * y + cy))

    img = Image.new("L", (w, h), 0)
    ImageDraw.Draw(img).polygon(poly, fill=255)
    arr = ((np.asarray(img) > 127) * 255).astype(np.uint8)
    Image.fromarray(arr).save(args.out, "PNG")

    ys, xs = np.nonzero(arr)
    summary = {
        "out": args.out,
        "template": args.template,
        "seed": args.seed,
        "canvas": [w, h],
        "area_px": int((arr > 127).sum()),
        "bbox": {"x": int(xs.min()), "y": int(ys.min()),
                 "width": int(xs.max() - xs.min() + 1),
                 "height": int(ys.max() - ys.min() + 1)},
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
