#!/usr/bin/env python3
"""Fit the subject into a designed shape and bake the protected source.

Inverts the mask-around-subject flow: the boundary shape is designed
first (design_shape.py) and the source photo is scaled and positioned
ONCE so its subject sits inside the shape's safe interior. The result is
an RGBA cutout whose alpha equals the shape mask; from then on the baked
cutout is the protected source and the bit-exact guarantee applies to it.
The original photo is recorded by SHA-256 for provenance.

Solved for the largest subject satisfying both constraints:
  1. the scaled photo fully covers the shape (no transparent holes), and
  2. the subject box lies inside the shape eroded by --inner-margin.

Usage:
    python fit_subject.py --shape shape.png --source photo.png \
        --out source_cutout.png --report fit-report.json \
        [--subject-box x,y,w,h] [--inner-margin 24] \
        [--headroom 0.95] [--max-upscale 1.5]

Exit codes: 0 = ok, 1 = no feasible fit, 2 = usage/IO error.
"""

import argparse
import hashlib
import json
import sys

import numpy as np
from PIL import Image, ImageFilter

SCALE_SCAN_STEPS = 48
OFFSET_SCAN_STEPS = 64


def sha256_of_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_subject_box(img):
    """Gradient-energy saliency box; override with --subject-box if wrong."""
    gray = np.asarray(img.convert("L"), dtype=np.float32)
    gx = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
    gy = np.abs(np.diff(gray, axis=0, prepend=gray[:1, :]))
    energy = Image.fromarray(np.minimum(gx + gy, 255).astype(np.uint8))
    energy = energy.filter(ImageFilter.GaussianBlur(max(4, min(img.size) // 40)))
    e = np.asarray(energy, dtype=np.float32)
    ys, xs = np.nonzero(e > e.mean() + 0.5 * e.std())
    if not len(xs):
        return 0, 0, img.width, img.height
    return (int(xs.min()), int(ys.min()),
            int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))


def erode(mask, margin):
    """Binary erosion via PIL MinFilter (kernel size must be odd)."""
    img = Image.fromarray((mask * 255).astype(np.uint8))
    return np.asarray(img.filter(ImageFilter.MinFilter(2 * margin + 1))) > 127


def rect_is_safe(bad_integral, x0, y0, x1, y1, shape):
    """True when [x0,x1)x[y0,y1) contains no unsafe pixel (integral image)."""
    h, w = shape
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h or x0 >= x1 or y0 >= y1:
        return False
    s = (bad_integral[y1, x1] - bad_integral[y0, x1]
         - bad_integral[y1, x0] + bad_integral[y0, x0])
    return s == 0


def solve_offset(scale, src_size, subject, shape_bbox, bad_integral,
                 safe_center, shape_dims):
    """Best photo offset at a given scale, or None when infeasible.

    Coverage pins the offset range; within it, scan for a position whose
    scaled subject box is fully safe, preferring the subject centered on
    the safe region.
    """
    sw, sh = (max(1, round(v * scale)) for v in src_size)
    x0, y0, x1, y1 = shape_bbox
    tx_lo, tx_hi = x1 + 1 - sw, x0
    ty_lo, ty_hi = y1 + 1 - sh, y0
    if tx_lo > tx_hi or ty_lo > ty_hi:
        return None
    bx, by, bw, bh = subject
    step_x = max(1, (tx_hi - tx_lo) // OFFSET_SCAN_STEPS)
    step_y = max(1, (ty_hi - ty_lo) // OFFSET_SCAN_STEPS)
    best, best_dist = None, None
    for ty in range(ty_lo, ty_hi + 1, step_y):
        for tx in range(tx_lo, tx_hi + 1, step_x):
            rx0 = tx + int(np.floor(bx * scale))
            ry0 = ty + int(np.floor(by * scale))
            rx1 = tx + int(np.ceil((bx + bw) * scale))
            ry1 = ty + int(np.ceil((by + bh) * scale))
            if not rect_is_safe(bad_integral, rx0, ry0, rx1, ry1, shape_dims):
                continue
            cx, cy = (rx0 + rx1) / 2.0, (ry0 + ry1) / 2.0
            dist = (cx - safe_center[0]) ** 2 + (cy - safe_center[1]) ** 2
            if best is None or dist < best_dist:
                best, best_dist = (tx, ty), dist
    return best


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shape", required=True, help="designed shape mask PNG")
    parser.add_argument("--source", required=True, help="source photo")
    parser.add_argument("--out", required=True, help="baked RGBA cutout PNG")
    parser.add_argument("--report", required=True, help="fit report JSON path")
    parser.add_argument("--subject-box", default=None,
                        help="x,y,w,h subject box in source pixels "
                             "(default: gradient-energy auto-detection)")
    parser.add_argument("--inner-margin", type=int, default=24,
                        help="erosion of the shape for the subject-safe "
                             "interior (default 24)")
    parser.add_argument("--headroom", type=float, default=0.95,
                        help="use this fraction of the maximal feasible "
                             "scale (default 0.95)")
    parser.add_argument("--max-upscale", type=float, default=1.5,
                        help="cap on photo upsampling (default 1.5)")
    args = parser.parse_args()

    try:
        src = Image.open(args.source).convert("RGB")
        shape = np.asarray(Image.open(args.shape).convert("L")) > 127
    except OSError as exc:
        print("cannot read input: %s" % exc, file=sys.stderr)
        return 2
    if not shape.any():
        print("shape mask is empty", file=sys.stderr)
        return 2

    if args.subject_box:
        try:
            bx, by, bw, bh = (int(v) for v in args.subject_box.split(","))
        except ValueError:
            print("--subject-box must be x,y,w,h integers", file=sys.stderr)
            return 2
        detection = "manual"
    else:
        bx, by, bw, bh = detect_subject_box(src)
        detection = "auto"

    safe = erode(shape, max(args.inner_margin, 1))
    if not safe.any():
        print("inner margin %d erases the whole shape interior"
              % args.inner_margin, file=sys.stderr)
        return 1
    bad = (~safe).astype(np.int64)
    bad_integral = np.zeros((shape.shape[0] + 1, shape.shape[1] + 1),
                            dtype=np.int64)
    bad_integral[1:, 1:] = bad.cumsum(0).cumsum(1)
    sy, sx = np.nonzero(safe)
    safe_center = (float(sx.mean()), float(sy.mean()))
    ys, xs = np.nonzero(shape)
    shape_bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))

    # coverage floor: the scaled photo must span the shape bbox
    s_min = max((shape_bbox[2] - shape_bbox[0] + 1) / src.width,
                (shape_bbox[3] - shape_bbox[1] + 1) / src.height)
    # fit ceiling: the scaled subject box must fit in the safe bbox
    s_max = min((sx.max() - sx.min() + 1) / bw,
                (sy.max() - sy.min() + 1) / bh,
                args.max_upscale)
    if s_min > s_max:
        print("no feasible scale: coverage needs >= %.3f but subject fit "
              "allows <= %.3f; use a larger shape canvas or a tighter "
              "subject box" % (s_min, s_max), file=sys.stderr)
        return 1

    subject = (bx, by, bw, bh)
    src_size = (src.width, src.height)
    scale = offset = None
    for s in np.linspace(s_max, s_min, SCALE_SCAN_STEPS):
        offset = solve_offset(s, src_size, subject, shape_bbox, bad_integral,
                              safe_center, shape.shape)
        if offset is not None:
            scale = float(s)
            break
    if offset is None:
        print("no feasible placement found; relax --inner-margin or use a "
              "wider shape template", file=sys.stderr)
        return 1

    # trade a sliver of subject size for breathing room, if still feasible
    eased = max(s_min, scale * args.headroom)
    if eased < scale:
        eased_offset = solve_offset(eased, src_size, subject, shape_bbox,
                                    bad_integral, safe_center, shape.shape)
        if eased_offset is not None:
            scale, offset = eased, eased_offset

    sw, sh = (max(1, round(v * scale)) for v in src_size)
    tx, ty = offset
    scaled = src.resize((sw, sh), Image.LANCZOS)
    canvas = np.zeros((shape.shape[0], shape.shape[1], 4), dtype=np.uint8)
    cx0, cy0 = max(tx, 0), max(ty, 0)
    cx1, cy1 = min(tx + sw, shape.shape[1]), min(ty + sh, shape.shape[0])
    canvas[cy0:cy1, cx0:cx1, :3] = np.asarray(scaled)[cy0 - ty:cy1 - ty,
                                                      cx0 - tx:cx1 - tx]
    canvas[..., 3] = shape * np.uint8(255)

    covered = np.zeros(shape.shape, dtype=bool)
    covered[cy0:cy1, cx0:cx1] = True
    holes = int((shape & ~covered).sum())
    if holes:
        print("scaled photo leaves %d shape pixels uncovered" % holes,
              file=sys.stderr)
        return 1

    Image.fromarray(canvas).save(args.out, "PNG")
    report = {
        "verified": True,
        "out": args.out,
        "canvas": [shape.shape[1], shape.shape[0]],
        "scale": round(scale, 4),
        "scaled_size": [sw, sh],
        "photo_offset": [tx, ty],
        "subject_detection": detection,
        "subject_box_source": [bx, by, bw, bh],
        "subject_box_out": [tx + int(round(bx * scale)),
                            ty + int(round(by * scale)),
                            int(round(bw * scale)), int(round(bh * scale))],
        "inner_margin": args.inner_margin,
        "headroom": args.headroom,
        "original_source_sha256": sha256_of_file(args.source),
        "original_source_size": [src.width, src.height],
        "out_sha256": sha256_of_file(args.out),
    }
    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
