# Script reference

All scripts need Python 3 with `numpy` and `Pillow`
(`pip install -r requirements.txt`). No other dependencies.

## Mask smoothing

```bash
# Chaikin corner cutting on an outline polygon, rasterized to a binary mask
python scripts/smooth_mask.py --polygon points.json --canvas 1024x1024 \
    --out mask.png --iterations 3

# Blur-smooth an existing rough mask (rounds corners, removes sawtooth)
python scripts/smooth_mask.py --mask rough-mask.png --out mask.png \
    --blur-radius 6 --passes 2
```

Always re-run preflight on the smoothed mask; smoothing helps meet the
geometry limits but does not guarantee them.

## Shape-first boundary design

```bash
# 1. design the boundary from the composition style
python scripts/design_shape.py --template leaf --canvas 900x1100 \
    --out shape.png --seed 7 [--fill 0.84] [--rotate 0]

# 2. scale and place the subject into the shape, bake the cutout
python scripts/fit_subject.py --shape shape.png --source photo.png \
    --out source_cutout.png --report fit-report.json \
    [--subject-box x,y,w,h] [--inner-margin 24]
```

`design_shape.py` builds an organic mask as a polar radius curve with
three octaves of random harmonic variation (templates: `leaf`, `pebble`,
`torn`, `brush`). Run preflight on the result; on a geometry failure try
another seed. `fit_subject.py` inverts the mask-around-subject flow: it
finds the largest scale and offset of the photo such that the photo fully
covers the shape AND the subject box (auto-detected by gradient energy,
or given with `--subject-box`) fits inside the shape eroded by
`--inner-margin`, then resamples the photo ONCE (Lanczos) and bakes an
RGBA cutout whose alpha equals the shape mask. The baked cutout is the
protected source from then on; the fit report records the original
photo's SHA-256, the scale, and the offset for provenance. The manifest
must not repeat the scale - restoration still forbids transforms.

## Environment and generation guides

Before an external model request:

```bash
python scripts/preflight_environment.py --source source.png \
  --final-size 1242x1660 --generation-size 1248x1664 \
  --model gpt-image-2 --endpoint https://example/v1/models \
  --ca-bundle /path/to/trusted-ca.pem --out environment.preflight.json
```

`build_generation_guide.py` renders a review-only final-canvas placement
guide. `build_transition_mask.py` emits an RGBA OpenAI-style edit mask whose
transparent pixels are sparse exterior transition sectors; it never marks
the protected subject editable.

`normalize_generation_output.py` checks the provider's actual returned size
and deterministically resizes it to the planned generation canvas before a
Stage B mask is submitted. Never assume the API honored the requested size.

`cache_generation.py` provides content-addressed `lookup`/`record` operations
for accepted Stage A/B artifacts. `generation_gate.py` enforces the attempt
budget. `preflight_stage_b.py` validates image/mask dimensions, binary alpha,
and protected-pixel opacity before a provider edit request.

## Preflight validation

```bash
python scripts/preflight_composition.py \
    --plan composition-plan.json \
    --mask mask.png \
    --out composition.preflight.json \
    --mask-preview mask-preview.png \
    --source source.png
```

Reads the plan, validates required fields, mode, `window.type`,
`edge_profile` (all `variation_scales` must be `true`), the `fusion` plan,
the `atmosphere` design layer (grammar enum, concrete `photo_echo_subjects`,
field/quiet shares in range, `quiet_texture`, edge treatment, structural
chromatic accent, micro-text length limits), the `seam` declaration in
`photo_echo` mode, and the `preview_review_requirements` checklist (all
entries must be `true`); loads the mask, rejects empty masks, and warns on
anti-aliased (non-binary) masks. Geometry checks: rectangularity plus the
perceptual rectangle gate (corner occupancy + mean side inset);
broken-contour checks; longest exact straight edge in horizontal, vertical,
and diagonal directions; longest near-straight segment at any angle (1 px
chord tolerance); regular periodic sawtooth on every contour. In organic
modes, any threshold violation exits with code 1. `photo_window` requires a
near-rectangular mask. `photo_echo` requires full-bleed coverage of the
canvas perimeter, exempts border-hugging boundary segments, and applies the
straightness/sawtooth/variation gates to the interior torn seam. Writes a
JSON report with `verified`, `errors`, `warnings`, and `mask_metrics`
(including `corner_occupancy`, `side_inset_ratios`, `visual_rectangle`,
`max_straight_any_angle_px`, and in photo_echo mode a `photo_echo` block
with `border_bleed_fraction`, per-side `edge_hug`, and per-seam metrics),
and optionally renders `mask-preview.png` (with `--source`, the preview
shows the real source content inside the protected region and a dimmed
source outside).

## Restore and verify

```bash
python scripts/restore_and_verify.py \
    --ai-base final_ai_base.png \
    --manifest manifest.json \
    --plan composition-plan.json \
    --out final.png \
    --report final.verification.json
```

The manifest points to the RGBA source cutout and its integer `placement`
(strict integers; floats, strings, and booleans are rejected) with
`alpha_policy: "nontransparent"`. Optional provenance fields: `mask` (path;
hashed and size-checked against the source) and `generation_prompt` or
`generation_prompt_file` (hashed). Only non-transparent source pixels are
pasted back. Scaling, rotation, and perspective transforms of the protected
region are rejected. With `--plan`, the manifest `placement` and `mode` must
match the preflight-approved plan. The script writes a PNG, re-reads it from
disk, compares SHA-256 of the protected pixels, and returns a non-zero exit
code with `verified=false` on any mismatch. The report records full
provenance: SHA-256 of the protected pixels, source file, mask file, plan
file, and generation prompt, plus `source_size`, `mask_size`,
`canvas_size`, and the plan's `source_crop` - so a swapped source or mask
is detectable after the fact. Usage/IO failures (exit code 2) also write a
`verified=false` report so a stale report can never be mistaken for a
fresh result.

## Visual review (evidence, not self-report)

```bash
# 1. render the evidence thumbnail
python scripts/visual_review.py --final final.png \
    --thumbnail final.thumbnail.png

# 2. inspect final.png AND final.thumbnail.png, then write
#    final-visual-review.json with honest verdicts

# 3. validate
python scripts/visual_review.py --check final-visual-review.json
```

`final-visual-review.json` required fields:

```json
{
  "review_image": "final.png",
  "thumbnail_image": "final.thumbnail.png",
  "rectangular_read": "pass",
  "sticker_border": "pass",
  "transition_blending": "fail",
  "edge_tactility": "pass",
  "micro_text_legible": "not_applicable",
  "shape_serves_motion": "pass",
  "no_default_oval_island": "pass",
  "review_notes": "transition shapes cluster too close to the boundary"
}
```

`edge_tactility` asks whether the boundary reads as a tactile paper edge
(torn fiber, fringe) rather than a clean digital cutout.
`micro_text_legible` asks whether the planned micro-text is correctly
spelled and legible (`not_applicable` when `micro_text` was `null`).
`shape_serves_motion` asks whether the protected shape has an intentional
directional relationship to the subject gesture or declared eye path.
`no_default_oval_island` asks whether the protected region avoids an
uninspired centered oval or evenly padded photo island. A geometrically safe
shape may still fail either design verdict.
Verdicts must be `"pass"` or `"fail"` - `fail` is legal and expected when
the render is not good enough. Any `fail` exits 1 with the instruction to
regenerate ONLY the Stage B transition layer; the verified protected
subject must never be regenerated. Referenced evidence images must exist.

## Unified runner

```bash
python scripts/run_compositor.py --workdir out \
    --plan composition-plan.json --mask mask.png --source source.png \
    --manifest manifest.json --ai-base final_ai_base.png \
    [--review final-visual-review.json] \
    [--generation-state generation-state.json]
```

Runs preflight -> restore+verify -> thumbnail -> review check in order,
stops at the first failure, and writes `pipeline-status.json` with
per-stage exit codes. Omit `--manifest/--ai-base` for a preflight-only run
before generation; omit `--review` to leave the visual review pending.

## Test coverage

Run `python -m unittest discover -s tests -v` (40 tests) from the
repository root. It covers: a free-form mask passing preflight;
rectangular masks, wobbly-edged "visual rectangles", long straight edges,
shallow diagonals, and regular sawtooth rejected in organic modes; `false`
checklist values, invalid `fusion` plans, and invalid `atmosphere` plans
(bad grammar, timid field shares, missing
`photo_echo_subjects`/`quiet_texture`, over-length micro-text) rejected;
`photo_window` accepting rectangles and rejecting organic masks;
`photo_echo` accepting a full-bleed mask with a torn seam and rejecting
straight seams, floating masks, and missing seam/window declarations -
while the same full-bleed mask still fails organic modes; anti-aliased
mask warnings; the source-overlay preview; non-integer placement
rejection; the restore round-trip with zero mismatch; plan/manifest
cross-checks; provenance fields (mask/prompt hashes, sizes, crop); report
files written on IO failure; visual-review schema, pass, and fail paths;
the unified runner's happy path, stop-on-failure, and failed-review
handling; and both smoothing modes of `smooth_mask.py`.
