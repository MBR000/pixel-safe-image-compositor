#!/usr/bin/env python3
"""Render a human/agent review guide for the final canvas mapping."""

import argparse
import json
import sys

from PIL import Image, ImageDraw


def parse_size(value):
    try:
        return tuple(int(v) for v in value.lower().split("x"))
    except (AttributeError, ValueError):
        raise argparse.ArgumentTypeError("size must be WxH")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", required=True)
    p.add_argument("--mask", required=True)
    p.add_argument("--canvas", required=True, type=parse_size)
    p.add_argument("--placement", required=True, help="x,y offset")
    p.add_argument("--final-crop-offset", default="0,0",
                   help="generation-to-final crop x,y; added to placement")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    try:
        ox, oy = (int(v) for v in args.placement.split(","))
        crop_x, crop_y = (int(v) for v in args.final_crop_offset.split(","))
        ox += crop_x
        oy += crop_y
        src = Image.open(args.source).convert("RGBA")
        mask = Image.open(args.mask).convert("L")
    except (OSError, ValueError) as exc:
        print("cannot read guide inputs: %s" % exc, file=sys.stderr); return 2
    if src.size != mask.size:
        print("source and mask sizes differ", file=sys.stderr); return 1
    cw, ch = args.canvas
    if ox < 0 or oy < 0 or ox + src.width > cw or oy + src.height > ch:
        print("placement exceeds canvas", file=sys.stderr); return 1
    # Neutral guide: source is visible only inside the protected mask; the
    # magenta buffer is an instruction artifact, not a generation input.
    cutout = src.copy(); cutout.putalpha(mask)
    guide = Image.new("RGBA", (cw, ch), (242, 237, 220, 255))
    guide.alpha_composite(cutout, (ox, oy))
    draw = ImageDraw.Draw(guide, "RGBA")
    draw.rectangle((ox - 24, oy - 24, ox + src.width + 24,
                    oy + src.height + 24), outline=(210, 45, 115, 130), width=2)
    guide.save(args.out, "PNG")
    report = {"verified": True, "canvas": [cw, ch], "source": list(src.size),
              "generation_placement": [ox, oy],
              "final_crop_offset": [crop_x, crop_y], "quiet_buffer_px": 24,
              "note": "magenta boundary is review-only and must not be generated"}
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
