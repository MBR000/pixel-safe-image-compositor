#!/usr/bin/env python3
"""Preflight provider, dependency, source, and image-size constraints.

This runs before any paid generation request. It never prints credentials.
An endpoint check treats HTTP 401/403 as reachable because authentication is
intentionally not sent by this diagnostic.
"""

import argparse
import importlib.util
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

from PIL import Image


def size(value):
    try:
        w, h = (int(v) for v in value.lower().split("x"))
        if w <= 0 or h <= 0:
            raise ValueError
        return [w, h]
    except (AttributeError, ValueError):
        raise argparse.ArgumentTypeError("size must be positive WxH")


def check_generation_size(canvas, model):
    if not canvas:
        return []
    w, h = canvas
    errors = []
    pixels = w * h
    if model == "gpt-image-2":
        if max(canvas) > 3840 or pixels < 655360 or pixels > 8294400:
            errors.append("generation canvas violates gpt-image-2 pixel bounds")
        if w % 16 or h % 16:
            errors.append("gpt-image-2 generation dimensions must be multiples of 16")
        if max(canvas) / min(canvas) > 3:
            errors.append("generation canvas ratio exceeds 3:1")
    return errors


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", required=True)
    p.add_argument("--source")
    p.add_argument("--final-size", type=size, required=True)
    p.add_argument("--generation-size", type=size)
    p.add_argument("--model", default="gpt-image-2")
    p.add_argument("--credential-env", default="MY_API_KEY")
    p.add_argument("--endpoint", help="optional unauthenticated TLS endpoint")
    p.add_argument("--ca-bundle", help="PEM bundle for endpoint TLS")
    args = p.parse_args()
    errors = []
    warnings = []
    source_info = None
    if args.source:
        try:
            with Image.open(args.source) as img:
                source_info = {"size": list(img.size), "mode": img.mode,
                               "has_alpha": "A" in img.getbands()}
        except (OSError, ValueError) as exc:
            errors.append("source cannot be read: %s" % exc)
    if args.generation_size:
        errors.extend(check_generation_size(args.generation_size, args.model))
        if args.generation_size != args.final_size:
            gw, gh = args.generation_size
            fw, fh = args.final_size
            if gw < fw or gh < fh:
                errors.append("generation canvas must contain final canvas for crop")
            else:
                warnings.append("generation canvas differs; record deterministic crop")
    for module in ("numpy", "PIL"):
        if importlib.util.find_spec(module) is None:
            errors.append("missing dependency: %s" % module)
    credential_present = bool(os.environ.get(args.credential_env))
    if not credential_present:
        errors.append("credential environment variable is missing: %s" % args.credential_env)
    tls = None
    if args.endpoint:
        try:
            context = ssl.create_default_context(cafile=args.ca_bundle)
            urllib.request.urlopen(args.endpoint, context=context, timeout=10)
            tls = True
        except urllib.error.HTTPError as exc:
            tls = True if exc.code in (401, 403) else False
            if not tls:
                errors.append("provider returned HTTP %d" % exc.code)
        except (OSError, ssl.SSLError, ValueError) as exc:
            tls = False
            errors.append("provider TLS/connectivity failed: %s" % exc)
    report = {"verified": not errors, "errors": errors, "warnings": warnings,
              "model": args.model, "final_canvas": args.final_size,
              "generation_canvas": args.generation_size,
              "source": source_info,
              "provider": {"endpoint": args.endpoint, "tls_verified": tls,
                           "credential_env": args.credential_env,
                           "credential_present": credential_present}}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2); fh.write("\n")
    print(json.dumps(report, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
