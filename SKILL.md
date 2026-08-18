---
name: pixel-safe-image-compositor
description: This skill should be used when compositing images where a visual AI designs the layout, background, and creative transitions, while programmatic mask restoration and SHA-256 pixel verification guarantee that a protected source region is never repainted by the AI. It supports subject_cutout, organic_context, and photo_window modes with preflight mask geometry validation.
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
6. Perform a final visual review against the `preview_review` checklist and
   write `final-visual-review.json`.

## Step 1: composition-plan.json

The AI must emit a JSON plan with ALL of these required fields:

| Field | Meaning |
|---|---|
| `mode` | One of `subject_cutout`, `organic_context`, `photo_window` |
| `focal_group` | The protected subject group that must be preserved |
| `eye_path` | Intended viewing path through the composition |
| `keep_context` | Source context elements to keep |
| `drop_context` | Source context elements to drop |
| `source_shape_candidates` | Candidate shapes considered for the protected silhouette |
| `selected_shape` | The chosen shape from the candidates |
| `source_crop` | Crop of the source used as the protected region |
| `placement` | Integer `{x, y, width, height}` placement on the canvas |
| `layout_budget` | Space budget per layout zone |
| `window` | Window config; for `photo_window` must set `type: "rectangle_mask"` |
| `edge_profile` | Edge construction spec (see below) |
| `transition` | Plan for AI-generated local transitions outside the protected edge |
| `preview_review` | Self-review checklist (see below) |

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

### preview_review (required keys, all must be checked before delivery)

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
- No long straight horizontal, vertical, or diagonal edges.
- No continuous straight edge longer than about 12% of the longest dimension
  of the protected region.
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

## Step 3: two-stage AI generation, then programmatic restore

1. Stage A: generate the paper, illustration field, and background only.
2. Stage B: generate the detached, locally open transition shapes OUTSIDE the
   protected region.
3. Stage C (program, not AI): `restore_and_verify.py` pastes back the protected
   source pixels and verifies them per pixel with SHA-256.

Never treat any AI output as evidence that the source pixels survived.

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
- AI-generated text.

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
`edge_profile` (all `variation_scales` must be `true`), and the
`preview_review` checklist (all entries must be `true`); loads the mask,
rejects empty masks, and warns on anti-aliased (non-binary) masks; computes
rectangularity; checks that horizontal and vertical contours are broken;
measures the longest continuous straight edge in horizontal, vertical, and
diagonal directions; detects regular periodic sawtooth on every contour. In
organic modes, any threshold violation exits with code 1. `photo_window`
requires a near-rectangular mask. Writes a JSON report with `verified`,
`errors`, `warnings`, and `mask_metrics`, and optionally renders
`mask-preview.png` (with `--source`, the preview shows the real source
content inside the protected region and a dimmed source outside).

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
`alpha_policy: "nontransparent"`. Only non-transparent source pixels are
pasted back. Scaling, rotation, and perspective transforms of the protected
region are rejected. With `--plan`, the manifest `placement` and `mode` must
match the preflight-approved plan. The script writes a PNG, re-reads it from
disk, compares SHA-256 of the protected pixels, and returns a non-zero exit
code with `verified=false` on any mismatch. The report also records the
SHA-256 of the source file (and of the plan file when given) for auditing.
Usage/IO failures (exit code 2) also write a `verified=false` report so a
stale report can never be mistaken for a fresh result.

## Deliverables

All final image outputs must be PNG. Deliver together:

- `composition-plan.json`
- `mask-preview.png`
- `final.png`
- `composition.preflight.json`
- `final.verification.json`
- `final-visual-review.json`

## Minimal validation for this skill

Run the test suite from the repository root:

```bash
python -m unittest discover -s tests -v
```

It covers: a free-form mask passing preflight; rectangular masks, long
straight edges, and regular sawtooth rejected in organic modes; `false`
checklist values rejected; `photo_window` accepting rectangles and rejecting
organic masks; anti-aliased mask warnings; the source-overlay preview;
non-integer placement rejection; the restore round-trip with zero mismatch;
plan/manifest cross-checks; report files written on IO failure; and both
smoothing modes of `smooth_mask.py`.
