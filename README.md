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
  - no evenly spaced spikes or regular sawtooth
  - boundary must vary at large / medium / small scales
  - quiet paper buffer outside the protected edge
  - AI transitions must be detached, locally open shapes — never a closed
    outline or a parallel band tracing the silhouette
- Two-stage AI generation (background first, detached transitions second),
  then a programmatic restore stage the AI never participates in
- JSON reports at every gate: `verified`, `errors`, `warnings`,
  `mask_metrics`, SHA-256 digests
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
│   ├── preflight_composition.py    # validate plan + mask BEFORE generation
│   └── restore_and_verify.py       # paste back + SHA-256 verify AFTER generation
├── .gitignore
└── LICENSE                         # MIT
```

## Installation

### As a Codex / agent skill

Clone or copy this directory into your agent's skills directory, e.g.:

```bash
git clone https://github.com/<your-account>/pixel-safe-image-compositor.git
cp -r pixel-safe-image-compositor <your-skills-dir>/
```

The agent loads `SKILL.md` automatically when a compositing task matches.

### Script dependencies

```bash
pip install numpy Pillow
```

## Usage

### 1. The visual AI writes a plan

The AI emits `composition-plan.json` describing `focal_group`, `eye_path`,
`keep_context` / `drop_context`, shape candidates, placement, `edge_profile`,
transition plan, and a `preview_review` checklist. See `SKILL.md` for the
full schema.

### 2. Preflight the plan and mask

```bash
python scripts/preflight_composition.py \
    --plan composition-plan.json \
    --mask mask.png \
    --out composition.preflight.json \
    --mask-preview mask-preview.png
```

Exit code 1 means fix the plan or mask before generating anything.
Rectangular masks are rejected unless the plan explicitly declares
`mode: photo_window` and `window.type: rectangle_mask`.

### 3. Generate with the AI (two stages)

- Stage A: paper, illustration field, background only
- Stage B: detached, locally open transition shapes outside the protected
  region

Every prompt must forbid: repainting the protected region, new people or
animals, sticker borders, continuous outlining, uniform halos, long straight
edges, regular sawtooth, tracing parallel to the protected outline,
full-image filters, and AI-generated text.

### 4. Restore and verify

```bash
python scripts/restore_and_verify.py \
    --ai-base final_ai_base.png \
    --manifest manifest.json \
    --out final.png \
    --report final.verification.json
```

The manifest pins the RGBA source cutout, its integer placement, and
`alpha_policy: "nontransparent"`. The script pastes back exactly the
non-transparent source pixels, writes `final.png`, re-reads it, and compares
SHA-256 of the protected pixels. Any mismatch: `verified=false`, non-zero
exit.

### 5. Deliver

- `composition-plan.json`
- `mask-preview.png`
- `final.png`
- `composition.preflight.json`
- `final.verification.json`
- `final-visual-review.json`

All image outputs are PNG.

## Validation

This skill ships with its guarantees tested:

- skill-creator `quick_validate.py` passes
- both scripts pass `py_compile`
- a free-form multi-scale mask passes preflight
- a rectangular mask is rejected in organic modes
- a mask with a long straight edge is rejected in organic modes
- a rectangular mask passes with an explicit `photo_window` declaration
- a restore round-trip produces a matching SHA-256

## License

MIT — see [LICENSE](LICENSE).
