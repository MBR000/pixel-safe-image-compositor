#!/usr/bin/env python3
"""Unified runner for the pixel-safe-image-compositor pipeline.

Runs every programmatic stage in order, records per-stage status, and stops
at the first failure. AI generation (Stage A/B) happens OUTSIDE this runner,
between preflight and restore; the runner validates everything around it:

    plan -> preflight -> [external AI generation] -> restore -> verify
         -> thumbnail -> visual review check

Usage:
    python run_compositor.py --workdir out \
        --plan composition-plan.json --mask mask.png [--source source.png] \
        [--manifest manifest.json --ai-base final_ai_base.png] \
        [--review final-visual-review.json]
        [--generation-state generation-state.json]

Stages run based on the inputs provided:
  - --plan/--mask            preflight (always required)
  - --manifest/--ai-base     restore + SHA-256 verify + evidence thumbnail
  - --review                 validate final-visual-review.json (fail allowed;
                             a fail verdict means regenerate Stage B only)

Artifacts written into --workdir:
    composition.preflight.json, mask-preview.png, final.png,
    final.verification.json, final.thumbnail.png, pipeline-status.json

Exit codes: 0 = all requested stages passed, 1 = a stage failed,
2 = usage error.
"""

import argparse
import json
import os
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))


def run_stage(status, name, argv, outputs):
    proc = subprocess.run([sys.executable] + argv, capture_output=True,
                          text=True)
    entry = {
        "stage": name,
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "outputs": outputs,
    }
    if proc.returncode != 0:
        entry["stderr"] = proc.stderr.strip()[-2000:]
    status["stages"].append(entry)
    sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return proc.returncode == 0


def finish(status, workdir, ok):
    status["ok"] = ok
    status_path = os.path.join(workdir, "pipeline-status.json")
    with open(status_path, "w", encoding="utf-8") as fh:
        json.dump(status, fh, indent=2)
        fh.write("\n")
    print(json.dumps({"pipeline_ok": ok, "status": status_path,
                      "stages": [(s["stage"], s["ok"])
                                 for s in status["stages"]]}, indent=2))
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workdir", required=True,
                        help="output directory for all artifacts")
    parser.add_argument("--plan", required=True, help="composition-plan.json")
    parser.add_argument("--mask", required=True, help="protected mask PNG")
    parser.add_argument("--source", default=None,
                        help="optional source image for the mask preview")
    parser.add_argument("--manifest", default=None, help="restore manifest")
    parser.add_argument("--ai-base", default=None,
                        help="AI-generated base image (Stage A + B output)")
    parser.add_argument("--review", default=None,
                        help="filled final-visual-review.json to validate")
    parser.add_argument("--generation-state", default=None,
                        help="optional external AI/fallback state JSON")
    args = parser.parse_args()

    if bool(args.manifest) != bool(args.ai_base):
        print("--manifest and --ai-base must be used together",
              file=sys.stderr)
        return 2
    os.makedirs(args.workdir, exist_ok=True)

    status = {"ok": False, "stages": []}
    wd = args.workdir

    if args.generation_state:
        try:
            with open(args.generation_state, encoding="utf-8") as fh:
                status["generation"] = json.load(fh)
        except (OSError, ValueError) as exc:
            print("cannot read --generation-state: %s" % exc,
                  file=sys.stderr)
            return 2

    preflight_out = os.path.join(wd, "composition.preflight.json")
    preview = os.path.join(wd, "mask-preview.png")
    argv = [os.path.join(SCRIPTS_DIR, "preflight_composition.py"),
            "--plan", args.plan, "--mask", args.mask,
            "--out", preflight_out, "--mask-preview", preview]
    if args.source:
        argv += ["--source", args.source]
    if not run_stage(status, "preflight", argv,
                     {"report": preflight_out, "mask_preview": preview}):
        return finish(status, wd, False)

    if not args.manifest:
        # Preflight-only run: generation has not happened yet.
        return finish(status, wd, True)

    final_png = os.path.join(wd, "final.png")
    verification = os.path.join(wd, "final.verification.json")
    argv = [os.path.join(SCRIPTS_DIR, "restore_and_verify.py"),
            "--ai-base", args.ai_base, "--manifest", args.manifest,
            "--plan", args.plan, "--out", final_png,
            "--report", verification]
    if not run_stage(status, "restore_and_verify", argv,
                     {"final": final_png, "report": verification}):
        return finish(status, wd, False)

    thumbnail = os.path.join(wd, "final.thumbnail.png")
    argv = [os.path.join(SCRIPTS_DIR, "visual_review.py"),
            "--final", final_png, "--thumbnail", thumbnail]
    if not run_stage(status, "thumbnail", argv, {"thumbnail": thumbnail}):
        return finish(status, wd, False)

    if args.review:
        argv = [os.path.join(SCRIPTS_DIR, "visual_review.py"),
                "--check", args.review]
        if not run_stage(status, "visual_review", argv,
                         {"review": args.review}):
            return finish(status, wd, False)
    else:
        status["stages"].append({
            "stage": "visual_review", "ok": None, "exit_code": None,
            "outputs": {},
            "note": "pending: review %s against the thumbnail, write "
                    "final-visual-review.json, re-run with --review"
                    % thumbnail,
        })

    return finish(status, wd, True)


if __name__ == "__main__":
    sys.exit(main())
