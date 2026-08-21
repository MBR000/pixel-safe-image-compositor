---
name: pixel-safe-image-compositor
description: This skill should be used when compositing images where a visual AI designs the layout, background, and creative transitions, while programmatic mask restoration and SHA-256 pixel verification guarantee that a protected source region is never repainted by the AI. It supports subject_cutout, organic_context, photo_window, and photo_echo modes with preflight mask geometry validation.
---

# Pixel-Safe Image Compositor

Let the visual AI own composition and background creativity, but never let
it touch the protected pixels. The AI plans and paints; the program
restores and verifies. If verification fails, the result is rejected - no
exceptions.

Core guarantee: the protected region of the final PNG is pixel-identical
to the source. An AI render is never accepted as proof of source fidelity.

## References (read on demand)

- `references/plan-schema.md` - full `composition-plan.json` schema with
  JSON examples (`design_intent`, `edge_profile`, `fusion`, `atmosphere`, `seam`,
  `preview_review_requirements`). Read BEFORE writing the plan.
- `references/geometry-gates.md` - hard mask-geometry gates per mode.
  Read before building the mask.
- `references/generation-guide.md` - Stage A/B guidance and the verbatim
  prompt-prohibition list. Read before writing any generation prompt.
- `references/scripts.md` - detailed script behavior, report fields, the
  visual-review JSON schema, and test coverage.
- `references/intake.md` - compact user intake, automatic defaults,
  generation budgets, and cache rules. Read before asking questions.

## Workflow

1. Run the compact intake in `references/intake.md`; write the resolved
   answers to `creative-brief.json`. Inspect source and environment instead
   of asking for facts that can be derived.
2. Run `scripts/preflight_environment.py` before any model request. It must
   pass dependency, credential, TLS/provider, source, and generation-size
   checks. A transport failure does not consume a generation attempt.
3. Write `composition-plan.json` per `references/plan-schema.md`
   (planning only, no pixels yet). Every new plan must include
   `design_intent`: choose a directional shape language, name the subject's
   motion axis, state the leading mass and trailing taper, cap the retained
   context budget, and explain why the shape supports the eye path.
4. Build the protected-region mask. Smooth it with
   `scripts/smooth_mask.py` (Chaikin corner cutting on a polygon, or
   blur-smoothing a rough mask). The mask must be binary (0/255):
   anti-aliased masks make the approved and restored shapes diverge.
   Shape-first alternative for organic modes: design the boundary from
   the composition style with `scripts/design_shape.py` (leaf, pebble,
   torn, brush templates), then scale and place the subject into it with
   `scripts/fit_subject.py`; the baked RGBA cutout becomes the protected
   source and the shape mask is used as-is.
5. Validate plan and mask:

   ```bash
   python scripts/preflight_composition.py --plan composition-plan.json \
       --mask mask.png --out composition.preflight.json \
       --mask-preview mask-preview.png --source source.png
   ```

   Exit code 1 means stop and fix. Never generate on a failed preflight.
6. Render `scripts/build_generation_guide.py` and review the final-canvas
   mapping. Generate Stage A once. For Stage B, use the exterior-only edit
   mask from `scripts/build_transition_mask.py`; never rely on coordinate
   text alone. Validate the provider's actual output dimensions and
   normalize them with `scripts/normalize_generation_output.py` before any
   mask-based edit. Cache accepted Stage A and retry Stage B at most twice.
   Every prompt includes the verbatim prohibition list. Before either paid
   request, use `scripts/generation_gate.py` to enforce the attempt budget.
   For Stage B, run `scripts/preflight_stage_b.py` after normalization and
   before sending the request. Use `scripts/cache_generation.py lookup` before
   Stage A; record only accepted artifacts with `record`.
7. Restore and verify:

   ```bash
   python scripts/restore_and_verify.py --ai-base final_ai_base.png \
       --manifest manifest.json --plan composition-plan.json \
       --out final.png --report final.verification.json
   ```

   Any pixel mismatch yields `verified=false` and a non-zero exit code;
   reject the result.
8. Evidence-based visual review: render the thumbnail with
   `scripts/visual_review.py --final final.png --thumbnail
   final.thumbnail.png`, inspect BOTH images, write
   `final-visual-review.json` with honest `pass`/`fail` verdicts, and
   validate it with `scripts/visual_review.py --check`. On any `fail`,
   regenerate ONLY the Stage B transition layer and repeat steps 5-6;
   never regenerate the verified protected subject.

`scripts/run_compositor.py --workdir out --plan ... --mask ...
--source ... [--manifest ... --ai-base ...] [--review ...]` runs all
programmatic stages in order and writes `pipeline-status.json`.

Generation is external to the runner. Record provider, model, prompt hashes,
cache hits, attempts, and fallback outcome in `generation-state.json`; pass it
to the runner with `--generation-state` so `pipeline-status.json` distinguishes
AI Stage B rejection from an accepted deterministic fallback.

## Choosing a mode

- `photo_echo` - preferred when the source is a full photograph with a
  usable content line (horizon, ridge): the photo runs full-bleed to the
  canvas edges and one torn seam separates it from the illustrated layer.
  Strongest "one continuous world on paper" read.
- `subject_cutout` / `organic_context` - isolated subjects on an organic
  free-form mask. Prefer these when the subject has a readable gesture or
  silhouette that can drive a directional shape.
- `photo_window` - only when an explicit rectangular photo frame is
  wanted.

## Hard rules (non-negotiable)

- The plan must contain ALL required fields. `photo_window` needs
  `window.type: "rectangle_mask"`; `photo_echo` needs
  `window.type: "torn_seam"` plus a `seam` `{anchor, side}` object
  anchored to a content line of the photo.
- Organic modes: no rectangles and no visually rectangular masks; no
  straight run longer than 12% of the longest protected dimension; no
  near-straight segment at any angle longer than 15%; no regular
  sawtooth; three-scale boundary variation; quiet paper buffer outside
  the edge. Full gates in `references/geometry-gates.md`.
- Design gate: do not use a centered oval, pebble, or evenly padded
  bounding-island as the default protected shape. The selected shape must
  have directional asymmetry tied to the subject's motion axis: a
  `motion_brush`, `leaf_sweep`, `wedge_sweep`, `counterform`, or
  `contour_echo` language. A geometrically safe blob can still fail visual
  review when it does not change the eye path or figure-ground.
- `photo_echo`: the mask covers at least 25% of the canvas perimeter;
  border-hugging segments are exempt from straightness checks; the
  interior torn seam must pass every organic gate; the declared
  `seam.side` must be an interior boundary.
- Atmosphere: the illustration redraws the concrete `photo_echo_subjects`
  (generic doodles are rejected); quiet zones are laid in with the
  planned `quiet_texture` (blank paper is rejected); exactly ONE
  structural chromatic accent; `micro_text` is the only permitted
  AI-generated text.
- Visual review must explicitly pass `shape_serves_motion` and
  `no_default_oval_island`; if either fails, redesign the protected shape
  before retrying Stage B. Do not polish a weak silhouette with extra fibers
  or color.
- Never treat AI output as evidence that the source pixels survived; the
  only proof is the SHA-256 report from `restore_and_verify.py`.
- Never start a paid request when environment or geometry preflight fails.
  Never regenerate accepted Stage A for a Stage B visual failure, and never
  pass a full-canvas Stage B edit mask for local exterior transitions.

## Deliverables

All final image outputs must be PNG. Deliver together:
`composition-plan.json`, `mask-preview.png`, `final.png`,
`final.thumbnail.png`, `composition.preflight.json`,
`final.verification.json`, `final-visual-review.json`, and
`pipeline-status.json` (when using the runner).

## Minimal validation for this skill

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Run the test command rather than relying on a hard-coded test count; the
suite includes the original pipeline coverage plus environment and guide
checks.
