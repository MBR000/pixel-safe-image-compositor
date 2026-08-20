#!/usr/bin/env python3
"""Normalize a provider image to the planned generation canvas."""

import argparse
import json
import sys

from PIL import Image


def size(value):
    try:
        w, h = (int(v) for v in value.lower().split("x"))
        if w <= 0 or h <= 0:
            raise ValueError
        return w, h
    except (AttributeError, ValueError):
        raise argparse.ArgumentTypeError("size must be positive WxH")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--input", required=True)
    p.add_argument("--expected-size", required=True, type=size)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    try:
        image = Image.open(args.input).convert("RGBA")
    except OSError as exc:
        print("cannot read provider output: %s" % exc, file=sys.stderr)
        return 2
    before = list(image.size)
    resized = tuple(before) != args.expected_size
    if resized:
        image = image.resize(args.expected_size, Image.Resampling.LANCZOS)
    image.save(args.out, "PNG")
    report = {"verified": image.size == args.expected_size,
              "input_size": before, "output_size": list(image.size),
              "resized": resized, "method": "lanczos" if resized else "identity"}
    print(json.dumps(report, indent=2))
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    sys.exit(main())
