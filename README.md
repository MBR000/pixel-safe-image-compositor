# pixel-safe-image-compositor

Let the visual AI own composition and background creativity — but never let it
touch the protected pixels. The AI plans and paints; the program restores and
verifies.

A Codex / agent skill for compositing images where a protected source region
(product cutout, person, artwork) must survive **pixel-identical** in the
final image. The visual AI decides the layout, background, and transition
creativity; deterministic scripts validate the mask geometry up front and
restore + SHA-256-verify the protected pixels at the end. An AI render is
never accepted as proof of source fidelity.

## Why

Image models love to "improve" whatever you paste in: logos get redrawn,
labels get re-typeset, faces drift. If your use case requires the source
region to remain provably untouched (e-commerce, brand assets, archival
material), prompting alone cannot guarantee it. This skill turns that
guarantee into code:

- **Preflight gate** — mask geometry is validated before any generation.
  Bad shapes (rectangles, long straight edges, unbroken contours) stop the
  pipeline with exit code 1 instead of producing a bad image.
- **Programmatic restore** — only non-transparent source pixels are pasted
  back at an integer offset. No scaling, rotation, or perspective transform.
- **Cryptographic verification** — the final PNG is re-read from disk and the
  protected pixels are compared with SHA-256. Any mismatch yields
  `verified=false` and a non-zero exit code.

## Features

- Three composition modes:
  - `subject_cutout` — clean cutout subject on a designed field
  - `organic_context` — subject blended into an organic illustrated scene
  - `photo_window` — explicit rectangular photo window (the only mode where
    a rectangle mask is legal)
- Hard geometry limits for organic modes, enforced in code:
  - no rectangles / rounded rectangles / regular torn edges
  - no continuous straight edge longer than ~12% of the protected region's
    longest dimension (horizontal, vertical, and diagonal are all measured)
  - no evenly spaced spikes or regular sawtooth (detected via periodic
    zigzag analysis of every contour, not just self-declared)
  - boundary must vary at large / medium / small scales
  - quiet paper buffer outside the protected edge
  - AI transitions must be detached, locally open shapes — never a closed
    outline or a parallel band tracing the silhouette
- Two-stage AI generation (background first, detached transitions second),
  then a programmatic restore stage the AI never participates in
- Plan/manifest cross-check: the restore stage can verify that the manifest
  executes exactly the preflight-approved plan (`--plan`)
- `smooth_mask.py` helper: Chaikin corner cutting for outline polygons, or
  blur smoothing for rough masks
- JSON reports at every gate: `verified`, `errors`, `warnings`,
  `mask_metrics`, SHA-256 digests of protected pixels, source file, and plan
- Minimal dependencies: Python 3 + `numpy` + `Pillow`. No network, no API
  keys, no machine-specific paths

## Repository layout

```
pixel-safe-image-compositor/
├── SKILL.md                        # the skill: full workflow, constraints, prompts
├── README.md
├── agents/
│   └── openai.yaml                 # Codex agent metadata
├── scripts/
│   ├── smooth_mask.py              # Chaikin / blur mask smoothing helper
│   ├── preflight_composition.py    # validate plan + mask BEFORE generation
│   └── restore_and_verify.py       # paste back + SHA-256 verify AFTER generation
├── tests/
│   └── test_pipeline.py            # end-to-end + unit tests
├── requirements.txt
├── .gitignore
└── LICENSE                         # MIT
```

## Installation

### As a Codex / agent skill

Clone or copy this directory into your agent's skills directory, e.g.:

```bash
git clone https://github.com/MBR000/pixel-safe-image-compositor.git
cp -r pixel-safe-image-compositor <your-skills-dir>/
```

The agent loads `SKILL.md` automatically when a compositing task matches.

### Script dependencies

```bash
pip install -r requirements.txt
```

## Usage

### 1. The visual AI writes a plan

The AI emits `composition-plan.json` describing `focal_group`, `eye_path`,
`keep_context` / `drop_context`, shape candidates, placement, `edge_profile`,
transition plan, and a `preview_review` checklist. See `SKILL.md` for the
full schema.

### 2. Build and smooth the mask

```bash
python scripts/smooth_mask.py --polygon points.json --canvas 1024x1024 \
    --out mask.png --iterations 3
# or smooth an existing rough mask:
python scripts/smooth_mask.py --mask rough-mask.png --out mask.png
```

The mask must be binary (0/255); preflight warns on anti-aliased masks.

### 3. Preflight the plan and mask

```bash
python scripts/preflight_composition.py \
    --plan composition-plan.json \
    --mask mask.png \
    --out composition.preflight.json \
    --mask-preview mask-preview.png \
    --source source.png
```

Exit code 1 means fix the plan or mask before generating anything.
Rectangular masks are rejected unless the plan explicitly declares
`mode: photo_window` and `window.type: rectangle_mask` (and a declared
`photo_window` must actually be rectangular). With `--source`, the mask
preview shows the real source content inside the protected region.

### 4. Generate with the AI (two stages)

- Stage A: paper, illustration field, background only
- Stage B: detached, locally open transition shapes outside the protected
  region

Every prompt must forbid: repainting the protected region, new people or
animals, sticker borders, continuous outlining, uniform halos, long straight
edges, regular sawtooth, tracing parallel to the protected outline,
full-image filters, and AI-generated text.

### 5. Restore and verify

```bash
python scripts/restore_and_verify.py \
    --ai-base final_ai_base.png \
    --manifest manifest.json \
    --plan composition-plan.json \
    --out final.png \
    --report final.verification.json
```

The manifest pins the RGBA source cutout, its strictly-integer placement,
and `alpha_policy: "nontransparent"`. With `--plan`, the manifest placement
and mode must match the preflight-approved plan. The script pastes back
exactly the non-transparent source pixels, writes `final.png`, re-reads it,
and compares SHA-256 of the protected pixels. Any mismatch:
`verified=false`, non-zero exit. IO failures also write a `verified=false`
report.

### 6. Deliver

- `composition-plan.json`
- `mask-preview.png`
- `final.png`
- `composition.preflight.json`
- `final.verification.json`
- `final-visual-review.json`

All image outputs are PNG.

## Validation

This skill ships with its guarantees tested (18 tests):

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Covered: free-form masks pass preflight; rectangles, long straight edges,
and regular sawtooth are rejected in organic modes; `false` checklist values
are rejected; `photo_window` accepts rectangles and rejects organic masks;
anti-aliased masks trigger a warning; the source-overlay preview renders
correctly; non-integer placement is rejected; the restore round-trip
verifies with zero mismatched pixels; plan/manifest cross-checks catch
divergence; IO failures still write a report; and both `smooth_mask.py`
modes produce binary masks that improve the geometry.

## License

MIT — see [LICENSE](LICENSE).
