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
  - no "visual rectangles": a perceptual gate combining rectangularity,
    corner occupancy, and mean side inset catches wobbly-edged shapes that
    still read as rectangles
  - no continuous straight edge longer than ~12% of the protected region's
    longest dimension (horizontal, vertical, and diagonal are all measured)
  - no near-straight segment at ANY angle longer than ~15% (tolerant chord
    fit catches shallow diagonals and jittered long edges)
  - no evenly spaced spikes or regular sawtooth (detected via periodic
    zigzag analysis of every contour, not just self-declared)
  - boundary must vary at large / medium / small scales
  - quiet paper buffer outside the protected edge
  - AI transitions must be detached, locally open shapes — never a closed
    outline or a parallel band tracing the silhouette
- Structured `fusion` plan: the AI must state where transition colors come
  from, where transitions attach, and how material continuity works - not
  just avoid forbidden artifacts
- Two-stage AI generation (background first, detached transitions second),
  then a programmatic restore stage the AI never participates in
- Plan/manifest cross-check: the restore stage can verify that the manifest
  executes exactly the preflight-approved plan (`--plan`)
- Evidence-based visual review: `visual_review.py` renders the thumbnail
  the reviewer must inspect and validates `final-visual-review.json`, where
  `fail` is a legal verdict that triggers a Stage-B-only regeneration
- Full provenance in the verification report: SHA-256 of protected pixels,
  source file, mask file, plan file, and generation prompt, plus source /
  mask / canvas sizes and the source crop
- `run_compositor.py`: unified runner (preflight -> restore -> thumbnail ->
  review check) with per-stage status in `pipeline-status.json`
- `smooth_mask.py` helper: Chaikin corner cutting for outline polygons, or
  blur smoothing for rough masks
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
│   ├── run_compositor.py           # unified pipeline runner
│   ├── smooth_mask.py              # Chaikin / blur mask smoothing helper
│   ├── preflight_composition.py    # validate plan + mask BEFORE generation
│   ├── restore_and_verify.py       # paste back + SHA-256 verify AFTER generation
│   └── visual_review.py            # evidence thumbnail + review validation
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
`keep_context` / `drop_context`, shape candidates, placement,
`edge_profile`, transition plan, a structured `fusion` plan (palette cues,
transition anchors, material continuity, density gradient), and the
`preview_review_requirements` commitments. See `SKILL.md` for the full
schema.

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
and `alpha_policy: "nontransparent"` (optionally also `mask` and
`generation_prompt` for provenance hashing). With `--plan`, the manifest
placement and mode must match the preflight-approved plan. The script
pastes back exactly the non-transparent source pixels, writes `final.png`,
re-reads it, and compares SHA-256 of the protected pixels. Any mismatch:
`verified=false`, non-zero exit. IO failures also write a `verified=false`
report.

### 6. Visual review with evidence

```bash
python scripts/visual_review.py --final final.png \
    --thumbnail final.thumbnail.png
# inspect both images, write final-visual-review.json, then:
python scripts/visual_review.py --check final-visual-review.json
```

Verdicts are `"pass"`/`"fail"` and `fail` is legal - it exits 1 with the
instruction to regenerate only the Stage B transition layer, never the
verified subject.

Or run every programmatic stage at once:

```bash
python scripts/run_compositor.py --workdir out \
    --plan composition-plan.json --mask mask.png --source source.png \
    --manifest manifest.json --ai-base final_ai_base.png \
    --review final-visual-review.json
```

### 7. Deliver

- `composition-plan.json`
- `mask-preview.png`
- `final.png`
- `final.thumbnail.png`
- `composition.preflight.json`
- `final.verification.json`
- `final-visual-review.json`
- `pipeline-status.json` (when using the runner)

All image outputs are PNG.

## Validation

This skill ships with its guarantees tested (32 tests):

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Covered: free-form masks pass preflight; rectangles, wobbly-edged "visual
rectangles", long straight edges, shallow diagonals, and regular sawtooth
are rejected in organic modes; `false` checklist values and invalid
`fusion` plans are rejected; `photo_window` accepts rectangles and rejects
organic masks; anti-aliased masks trigger a warning; the source-overlay
preview renders correctly; non-integer placement is rejected; the restore
round-trip verifies with zero mismatched pixels; plan/manifest cross-checks
catch divergence; provenance fields (mask/prompt hashes, sizes, crop) are
recorded; IO failures still write a report; visual-review schema, pass, and
fail paths behave correctly; the unified runner passes end to end, stops on
preflight failure, and fails on a failed review; and both `smooth_mask.py`
modes produce binary masks that improve the geometry.

## License

MIT — see [LICENSE](LICENSE).
