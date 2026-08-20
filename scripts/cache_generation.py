#!/usr/bin/env python3
"""Content-addressed cache for accepted generation artifacts.

The cache stores accepted artifacts under an ignored cache directory. It is
keyed by source/plan/prompt hashes, model, and generation canvas so an
unrelated prompt or canvas can never reuse an old Stage A result.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canvas(value):
    try:
        w, h = (int(v) for v in value.lower().split("x"))
        if w <= 0 or h <= 0:
            raise ValueError
        return [w, h]
    except (AttributeError, ValueError):
        raise argparse.ArgumentTypeError("canvas must be positive WxH")


def cache_key(args):
    payload = {"source_sha256": sha256(args.source),
               "plan_sha256": sha256(args.plan),
               "prompt_sha256": sha256(args.prompt),
               "model": args.model, "generation_canvas": args.canvas}
    encoded = json.dumps(payload, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), payload


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("action", choices=("lookup", "record"))
    p.add_argument("--stage", choices=("stage-a", "stage-b"), required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--plan", required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--canvas", required=True, type=canvas)
    p.add_argument("--cache-dir", required=True)
    p.add_argument("--artifact", help="artifact to record")
    args = p.parse_args()
    try:
        key, fields = cache_key(args)
    except OSError as exc:
        print("cannot hash cache inputs: %s" % exc, file=sys.stderr)
        return 2
    entry_dir = os.path.join(args.cache_dir, key, args.stage)
    metadata_path = os.path.join(entry_dir, "metadata.json")
    artifact_path = os.path.join(entry_dir, "artifact.png")
    hit = os.path.isfile(metadata_path) and os.path.isfile(artifact_path)
    if args.action == "record":
        if not args.artifact or not os.path.isfile(args.artifact):
            print("--artifact must point to an existing file", file=sys.stderr)
            return 2
        os.makedirs(entry_dir, exist_ok=True)
        shutil.copy2(args.artifact, artifact_path)
        metadata = {"key": key, "stage": args.stage, "fields": fields,
                    "artifact": artifact_path}
        with open(metadata_path, "w", encoding="utf-8") as fh:
            json.dump(metadata, fh, indent=2); fh.write("\n")
        hit = True
    report = {"verified": hit, "cache_hit": hit, "key": key,
              "stage": args.stage, "metadata": metadata_path if hit else None,
              "artifact": artifact_path if hit else None, "fields": fields}
    print(json.dumps(report, indent=2))
    return 0 if hit else 1


if __name__ == "__main__":
    sys.exit(main())
