---
name: pixel-safe-image-compositor
description: This skill should be used when compositing images where a visual AI designs the layout, background, and creative transitions, while programmatic mask restoration and SHA-256 pixel verification guarantee that a protected source region is never repainted by the AI. It supports subject_cutout, organic_context, photo_window, and photo_echo modes with preflight mask geometry validation.
---

# Pixel-Safe Image Compositor

Let the visual AI own composition and background creativity, but never let it
touch the protected pixels. The AI plans and paints; the program restores and
verifies. If verification fails, the result is rejected - no exceptions.

Core guarantee: the protected region of the final PNG is pixel-identical to the
source. An AI render is never accepted as proof of source fidelity.

## Workflow overview

1. The visual AI outputs `composition-plan.json` (planning only, no pixels yet).
2. Build the protected-region mask. Use `scripts/smooth_mask.py` to apply
   Chaikin corner cutting to an outline polygon, or to blur-smooth a rough
   mask. The mask must be binary (0/255): preflight binarizes at >127 while
   restore pastes source alpha>0, so anti-aliased masks make the approved
   and restored shapes diverge.
3. Run `scripts/preflight_composition.py` to validate the plan and the mask.
   Pass `--source` so the mask preview shows the real source content.
   Fix all errors before any generation. Exit code 1 means stop.
4. Generate with the AI in two stages (see below).
5. Run `scripts/restore_and_verify.py` with `--plan composition-plan.json`
   to paste back the protected pixels, confirm the manifest executes the
   approved plan, and verify with SHA-256. Any mismatch yields
   `verified=false` and a non-zero exit code.
6. Evidence-based visual review: render the thumbnail with
   `scripts/visual_review.py --final final.png --thumbnail
   final.thumbnail.png`, inspect BOTH images, and write
   `final-visual-review.json` with honest `pass`/`fail` verdicts (see
   below). Validate it with `scripts/visual_review.py --check`. On any
   `fail`, regenerate ONLY the Stage B transition layer and repeat steps
   5-6; never regenerate the verified protected subject.

`scripts/run_compositor.py` runs all programmatic stages in order and
records per-stage status in `pipeline-status.json`.

## Choosing a mode

Prefer `photo_echo` when the source is a full photograph with a usable
horizon, ridge, or other content line: the photo runs full-bleed to the
canvas edges and only one torn seam separates it from the illustrated
layer. It produces the strongest "one continuous world on paper" read.
Use `subject_cutout` / `organic_context` for isolated subjects, and
`photo_window` only when an explicit rectangular photo frame is wanted.

## Step 1: composition-plan.json

The AI must emit a JSON plan with ALL of these required fields:

| Field | Meaning |
|---|---|
| `mode` | One of `subject_cutout`, `organic_context`, `photo_window`, `photo_echo` |
| `focal_group` | The protected subject group that must be preserved |
| `eye_path` | Intended viewing path through the composition |
| `keep_context` | Source context elements to keep |
| `drop_context` | Source context elements to drop |
| `source_shape_candidates` | Candidate shapes considered for the protected silhouette |
| `selected_shape` | The chosen shape from the candidates |
| `source_crop` | Crop of the source used as the protected region |
| `placement` | Integer `{x, y, width, height}` placement on the canvas |
| `layout_budget` | Space budget per layout zone |
| `window` | Window config; `photo_window` needs `type: "rectangle_mask"`, `photo_echo` needs `type: "torn_seam"` |
| `edge_profile` | Edge construction spec (see below) |
| `transition` | Plan for AI-generated local transitions outside the protected edge |
| `fusion` | Structured blending plan (see below) |
| `atmosphere` | Editorial-collage design layer (see below) |
| `preview_review_requirements` | Pre-generation commitments (see below) |
| `seam` | photo_echo only: `{anchor, side}` for the torn seam (see below) |

### edge_profile (required keys)

```json
{
  "construction": "free_curve",
  "smoothing": "chaikin_corner_cutting",
  "variation_scales": {"large": true, "medium": true, "small": true},
  "quiet_buffer_px": 24,
  "no_sawtooth": true,
  "detached_transition": true
}
```

- `variation_scales` must include `large`, `medium`, and `small`.
- `no_sawtooth` must be `true`; `detached_transition` must be `true`.
- `quiet_buffer_px` is the quiet paper buffer kept outside the protected edge.

### fusion (required keys)

Forces the AI to plan blending, not just avoid forbidden artifacts. It must
answer: where the transition colors come from, where transitions attach,
how the material stays continuous, and why density varies with distance.

```json
{
  "fusion": {
    "source_palette_cues": ["low-saturation blue-green mountain tones",
                            "warm ochre from the subject"],
    "transition_anchors": ["upper mountain ridge", "lower paper texture"],
    "material_continuity": "paper grain continues across transition",
    "transition_density": "sparse near subject, denser farther away"
  }
}
```

`source_palette_cues` and `transition_anchors` must be non-empty lists of
strings; `material_continuity` and `transition_density` must be non-empty
strings.

### atmosphere (required keys)

The design layer that separates an editorial collage from "a photo pasted
on cream paper". Adapted from the gathered-scenes zine approach; every
tactile treatment lives strictly OUTSIDE the protected pixels.

```json
{
  "atmosphere": {
    "illustration_grammar": "field_led",
    "photo_echo_subjects": ["rider silhouette", "lake pavilion",
                            "mountain ridge line"],
    "illustration_field_share": 0.55,
    "quiet_share": 0.65,
    "quiet_texture": "pale grey-green wash over visible paper grain",
    "edge_treatment": "torn_paper_fibrous",
    "chromatic_accent": {
      "hue": "clean tomato red",
      "integration_mode": "directional_rhythm",
      "structural_role": "route line carries the eye from the ghost summit down to the subject"
    },
    "micro_text": {
      "text": "The long ascent",
      "placement": "upper-left quiet paper, typewriter serif"
    }
  }
}
```

- `illustration_grammar`: one of `silhouette_led`, `contour_led`,
  `field_led`, `rhythm_led`, `cut_paper_led`. Pick ONE primary grammar.
- `photo_echo_subjects`: non-empty list of CONCRETE elements from the
  photo that the illustration layer redraws in the chosen grammar (the
  subject's silhouette, a building, the horizon, the sun). This is the
  core of the zine look: the illustration is the photo's echo - the same
  scene spoken in a second, graphic language. Generic doodles unrelated
  to the photo are rejected by preflight and read as decoration.
- `illustration_field_share`: 0.25-0.80 of the canvas. A small dotted motif
  in a corner plus two brush marks is a timid peripheral doodle, not a
  field - preflight rejects shares below 0.25. Enlarge the field before
  adding detail.
- `quiet_share`: 0.45-0.90. Most of the illustration field stays LOW
  CONTRAST - but quiet is a material, not a void.
- `quiet_texture`: required description of what the quiet zones are made
  of: watercolor washes, halftone grain, paper fiber, faint underprint.
  Blank untextured paper is rejected; the reference works fill their
  "empty" areas with low-contrast material that carries the atmosphere.
- `edge_treatment`: `torn_paper_fibrous` (default; irregular hand-ripped
  contour with a narrow fringe of paper fibers painted by the AI along the
  OUTSIDE of the protected boundary), `soft_fiber_fringe`, or
  `smooth_curve`. The tear must read as a real paper object, not a clean
  digital cutout. The fibrous band lives entirely in the quiet buffer;
  protected pixels are restored bit-exact regardless.
- `chromatic_accent`: exactly ONE added high-chroma hue doing compositional
  work. `hue` is an exact color (e.g. "clean tomato red", "opaque
  ultramarine" - never "muted" or "pale"); `integration_mode` is one of
  `source_continuation`, `selective_replacement`, `underprint_passage`,
  `counterform`, `directional_rhythm`; `structural_role` must pass the
  removal test: if deleting the hue would not change balance, eye path, or
  figure-ground, redesign it. A detached color patch "to feel designed" is
  forbidden.
- `micro_text`: one quiet editorial line, or `null` to opt out explicitly.
  `text` is at most 5 English words or 8 Han characters; `placement` names
  a quiet-paper area outside the protected region. Render as small
  typewriter/letterpress lettering in charcoal or brown-black; it is the
  resting point of the eye path, never a headline. This is the ONLY
  permitted AI-generated text.

### seam (required for photo_echo)

```json
{ "seam": { "anchor": "lake horizon", "side": "top" } }
```

- `anchor` names the CONTENT LINE in the photo that the tear follows
  (horizon, ridge, rooftop line). The seam is not an arbitrary curve: it
  sits on a structural line of the photo so the illustrated layer beyond
  it continues the same scene and the tear reads as "paper ripped open to
  reveal the real world".
- `side`: which boundary of the protected region is the torn seam
  (`left`, `right`, `top`, `bottom`). All other photo edges run full-bleed
  to the canvas.

### preview_review_requirements (required keys, all must be `true`)

These are pre-generation COMMITMENTS, not proof. The post-generation proof
is `final-visual-review.json` (Step 4), where `fail` is a legal verdict.

- `keep_context_complete`
- `selected_shape_readable_at_thumbnail`
- `no_closed_outline`
- `no_uniform_halo`
- `no_sawtooth`
- `quiet_buffer_visible`
- `detached_transition_shapes`
- `quiet_space_supports_eye_path`

## Step 2: modes and hard geometry limits

### subject_cutout and organic_context

For these two modes the mask edge MUST obey all of the following:

- No rectangles, rounded rectangles, or regular torn edges.
- No visually rectangular shapes: even below the hard rectangularity
  threshold, a mask is rejected when it is fairly full
  (rectangularity >= 0.70), all four bbox corners are occupied
  (corner occupancy >= 0.85), and every side hugs the bbox line on average
  (mean side inset <= 6%). Wobbly edges on a rectangle still read as a
  rectangle.
- No long straight horizontal, vertical, or diagonal edges.
- No continuous straight edge longer than about 12% of the longest dimension
  of the protected region.
- No near-straight segment at ANY angle (within 1 px of a straight chord)
  longer than 15% of the longest dimension - shallow diagonals and jittered
  long edges are caught too.
- No evenly spaced spikes and no regular sawtooth.
- The mask must be a smooth free-form curve.
- After generation, the mask must be smoothed with curve smoothing or corner
  cutting, e.g. Chaikin corner cutting or a spline.
- The boundary must vary at three scales: large, medium, and small.
- A quiet paper buffer must be preserved outside the protected edge.
- AI-generated transitions must be detached, locally open shapes away from the
  boundary. Never stroke along the full outline and never paint parallel
  bands tracing it.

### photo_window

A rectangular window is allowed ONLY when the plan explicitly declares:

```json
{ "mode": "photo_window", "window": { "type": "rectangle_mask" } }
```

Without both declarations, a rectangular mask is rejected by preflight.
Conversely, a `photo_window` plan requires a near-rectangular mask
(rectangularity >= 0.98); declaring `photo_window` with an organic mask is
also rejected.

### photo_echo

The zine layout: the protected photo runs FULL-BLEED to the canvas edges
(typically three sides) and one organic torn seam separates it from the
illustrated paper layer. Requires:

```json
{ "mode": "photo_echo", "window": { "type": "torn_seam" },
  "seam": { "anchor": "lake horizon", "side": "top" } }
```

Geometry gates enforced by preflight:

- The mask must cover at least 25% of the canvas perimeter (full-bleed);
  a floating shape must use an organic mode instead.
- Boundary segments lying ON the canvas border are exempt from all
  straightness checks - that is the point of full-bleed. The
  rectangularity and visual-rectangle gates do not apply in this mode.
- Every INTERIOR boundary segment (the torn seam) must read as a
  hand-torn edge: no straight run longer than 12% of the longest
  dimension, no near-straight segment at any angle longer than 15%, no
  regular sawtooth, and real variation (a flat seam is not a tear).
- The declared `seam.side` must actually be an interior boundary, not a
  canvas edge.

## Step 3: two-stage AI generation, then programmatic restore

1. Stage A: generate the paper, the LARGE illustration field (per
   `atmosphere.illustration_grammar` and `illustration_field_share`), the
   chromatic accent structure, and the background. The illustration MUST
   redraw the planned `photo_echo_subjects` - the photo's own subjects,
   horizon, buildings, sun - in the chosen grammar, at meaningful scale.
   In `photo_echo` mode the illustrated layer continues the photo's scene
   across the seam: the `seam.anchor` content line flows through the tear
   and the same landmarks appear on both sides in two languages. Quiet
   zones are laid in with the planned `quiet_texture` (washes, halftone
   grain, paper fiber) - never left as blank untextured paper.
2. Stage B: generate the detached, locally open transition shapes, the
   torn-paper fibrous edge along the OUTSIDE of the protected boundary (in
   `photo_echo`, along the seam), and the micro-text line (when planned) -
   all strictly outside the protected region.
3. Stage C (program, not AI): `restore_and_verify.py` pastes back the protected
   source pixels and verifies them per pixel with SHA-256.

Never treat any AI output as evidence that the source pixels survived.
The torn edge, fiber fringe, speckles, and every other tactile treatment
are painted outside the protected pixels; the restore stage overwrites
anything that strayed inside, so plan the tear to survive restoration.

### Prompt prohibitions (include verbatim in every generation prompt)

The generation prompt must explicitly forbid:

- repainting the protected region;
- adding new people or animals;
- sticker-style borders;
- continuous outlining;
- uniform halos;
- long straight edges;
- regular sawtooth;
- tracing parallel to the protected outline;
- full-image filters;
- AI-generated text other than the single planned `micro_text` line;
- timid peripheral doodles instead of a real illustration field;
- illustration content unrelated to the photo - the field must redraw the
  planned `photo_echo_subjects`;
- blank untextured quiet zones - lay in the planned `quiet_texture`;
- detached decorative color patches unrelated to source geometry;
- clean digital clipping edges where a torn-paper edge was planned.

## Scripts

All scripts need Python 3 with `numpy` and `Pillow`
(`pip install -r requirements.txt`). No other dependencies.

### Mask smoothing

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

### Preflight validation

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

### Restore and verify

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

### Visual review (evidence, not self-report)

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
  "review_notes": "transition shapes cluster too close to the boundary"
}
```

`edge_tactility` asks whether the boundary reads as a tactile paper edge
(torn fiber, fringe) rather than a clean digital cutout.
`micro_text_legible` asks whether the planned micro-text is correctly
spelled and legible (`not_applicable` when `micro_text` was `null`).
Verdicts must be `"pass"` or `"fail"` - `fail` is legal and expected when
the render is not good enough. Any `fail` exits 1 with the instruction to
regenerate ONLY the Stage B transition layer; the verified protected
subject must never be regenerated. Referenced evidence images must exist.

### Unified runner

```bash
python scripts/run_compositor.py --workdir out \
    --plan composition-plan.json --mask mask.png --source source.png \
    --manifest manifest.json --ai-base final_ai_base.png \
    [--review final-visual-review.json]
```

Runs preflight -> restore+verify -> thumbnail -> review check in order,
stops at the first failure, and writes `pipeline-status.json` with
per-stage exit codes. Omit `--manifest/--ai-base` for a preflight-only run
before generation; omit `--review` to leave the visual review pending.

## Deliverables

All final image outputs must be PNG. Deliver together:

- `composition-plan.json`
- `mask-preview.png`
- `final.png`
- `final.thumbnail.png`
- `composition.preflight.json`
- `final.verification.json`
- `final-visual-review.json`
- `pipeline-status.json` (when using the runner)

## Minimal validation for this skill

Run the test suite from the repository root:

```bash
python -m unittest discover -s tests -v
```

It covers: a free-form mask passing preflight; rectangular masks,
wobbly-edged "visual rectangles", long straight edges, shallow diagonals,
and regular sawtooth rejected in organic modes; `false` checklist values,
invalid `fusion` plans, and invalid `atmosphere` plans (bad grammar, timid
field shares, missing `photo_echo_subjects`/`quiet_texture`, over-length
micro-text) rejected; `photo_window` accepting rectangles and rejecting
organic masks; `photo_echo` accepting a full-bleed mask with a torn seam
and rejecting straight seams, floating masks, and missing seam/window
declarations - while the same full-bleed mask still fails organic modes;
anti-aliased mask warnings; the source-overlay preview; non-integer
placement rejection; the restore round-trip with zero mismatch;
plan/manifest cross-checks; provenance fields (mask/prompt hashes, sizes,
crop); report files written on IO failure; visual-review schema, pass, and
fail paths; the unified runner's happy path, stop-on-failure, and
failed-review handling; and both smoothing modes of `smooth_mask.py`.
