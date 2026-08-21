#!/usr/bin/env python3
"""Build a full-bleed photo_echo mask with one content-line torn seam."""

import argparse
import json
import sys

import numpy as np
from PIL import Image, ImageFilter

SIDES = ("left", "right", "top", "bottom")
ANCHORS = ("horizon", "ridge", "tabletop", "roofline", "gesture")


def parse_size(value):
    try:
        return tuple(int(v) for v in value.lower().split("x"))
    except (AttributeError, ValueError):
        raise argparse.ArgumentTypeError("size must be WxH")


def smooth_noise(rng, length, radius):
    values = rng.normal(0.0, 1.0, max(8, length))
    kernel = np.ones(max(3, radius), dtype=float)
    kernel /= kernel.sum()
    return np.convolve(values, kernel, mode="same")[:length]


def seam_profile(length, base, amplitude, seed, anchor):
    """Return an asymmetric seam with one deliberate broad gesture."""
    rng = np.random.default_rng(seed)
    t = np.linspace(0.0, 1.0, length)
    phase = rng.uniform(0, 2 * np.pi)
    bend = np.sin(2 * np.pi * (0.72 * t + phase / (2 * np.pi)))
    if anchor in ("ridge", "roofline"):
        bend += 0.42 * np.sin(4 * np.pi * t + phase * 0.7)
    elif anchor == "tabletop":
        bend += 0.26 * np.cos(3 * np.pi * t + phase)
    elif anchor == "gesture":
        bend += 0.38 * (t - 0.5) + 0.18 * np.sin(3 * np.pi * t + phase)
    else:
        bend += 0.18 * np.sin(3 * np.pi * t + phase)
    medium = smooth_noise(rng, length, max(9, length // 20))
    medium /= max(np.max(np.abs(medium)), 1.0)
    sparse = smooth_noise(rng, length, max(3, length // 90))
    sparse /= max(np.max(np.abs(sparse)), 1.0)
    taper = np.sin(np.pi * np.clip(t, 0, 1)) ** 0.55
    profile = base + amplitude * (0.62 * bend + 0.28 * medium +
                                  0.10 * sparse * taper)
    return np.rint(profile).astype(int)


def build_mask(width, height, side, base, amplitude, seed, anchor):
    mask = np.zeros((height, width), dtype=np.uint8)
    if side in ("top", "bottom"):
        seam = np.clip(seam_profile(width, base, amplitude, seed, anchor),
                       8, height - 8)
        for x, y in enumerate(seam):
            mask[y:, x] = 255 if side == "top" else 0
            if side == "bottom":
                mask[:y, x] = 255
    else:
        seam = np.clip(seam_profile(height, base, amplitude, seed, anchor),
                       8, width - 8)
        for y, x in enumerate(seam):
            mask[y, x:] = 255 if side == "left" else 0
            if side == "right":
                mask[y, :x] = 255
    if side in ("top", "bottom"):
        mask[:, 0] = 255
        mask[:, -1] = 255
        mask[-1 if side == "top" else 0, :] = 255
    else:
        mask[0, :] = 255
        mask[-1, :] = 255
        mask[:, -1 if side == "left" else 0] = 255
    image = Image.fromarray(mask).filter(ImageFilter.MaxFilter(3))
    return (np.asarray(image) > 127).astype(np.uint8) * 255


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--canvas", required=True, type=parse_size)
    parser.add_argument("--side", choices=SIDES, default="top")
    parser.add_argument("--anchor", choices=ANCHORS, default="horizon")
    parser.add_argument("--base", type=int, default=None)
    parser.add_argument("--amplitude", type=int, default=None)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    width, height = args.canvas
    cross = height if args.side in ("top", "bottom") else width
    base = args.base if args.base is not None else int(cross * 0.42)
    amplitude = (args.amplitude if args.amplitude is not None
                 else max(48, int(cross * 0.16)))
    if not (0 < base < cross) or amplitude < 8:
        print("base must be inside the canvas and amplitude must be >= 8",
              file=sys.stderr)
        return 2
    mask = build_mask(width, height, args.side, base, amplitude, args.seed,
                      args.anchor)
    Image.fromarray(mask).save(args.out, "PNG")
    print(json.dumps({
        "out": args.out, "canvas": [width, height], "side": args.side,
        "anchor": args.anchor, "base": base, "amplitude": amplitude,
        "seed": args.seed, "mode": "photo_echo", "window": "torn_seam",
        "full_bleed": True,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
