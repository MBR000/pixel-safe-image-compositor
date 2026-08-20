#!/usr/bin/env python3
"""Decide whether a paid Stage A/B request is still allowed."""

import argparse
import json
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--state", required=True)
    p.add_argument("--stage", choices=("stage-a", "stage-b"), required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    try:
        with open(args.state, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError) as exc:
        print("cannot read generation state: %s" % exc, file=sys.stderr)
        return 2
    if args.stage == "stage-a":
        used = int(state.get("stage_a_attempts_used", 0))
        limit = int(state.get("stage_a_max_attempts", 1))
        reasons = [] if used < limit else ["Stage A attempt budget exhausted"]
    else:
        used = int(state.get("stage_b_attempts_used", 0))
        limit = int(state.get("stage_b_max_attempts", 2))
        reasons = []
        if int(state.get("stage_a_attempts_used", 0)) < 1:
            reasons.append("Stage A must complete before Stage B")
        if used >= limit:
            reasons.append("Stage B attempt budget exhausted")
    report = {"allowed": not reasons, "stage": args.stage,
              "attempts_used": used, "attempt_limit": limit, "reasons": reasons}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2); fh.write("\n")
    print(json.dumps(report, indent=2))
    return 0 if not reasons else 1


if __name__ == "__main__":
    sys.exit(main())
