# composition-plan.json — full schema

Read this before writing the plan. Preflight rejects any missing or
invalid field.

## Required top-level fields

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

## generation_contract (recommended)

Record generation-only canvas mapping and retry policy separately from the
pixel restoration placement. Older plans remain valid without this block.

```json
{
  "generation_contract": {
    "final_canvas": {"width": 1242, "height": 1660},
    "generation_canvas": {"width": 1248, "height": 1664},
    "final_crop": {"x": 3, "y": 2, "width": 1242, "height": 1660},
    "generation_placement": {"x": 439, "y": 612, "width": 370, "height": 442},
    "stage_a_max_attempts": 1,
    "stage_b_max_attempts": 2,
    "stage_b_mask_semantics": "openai-transparent-editable",
    "cache_key_fields": ["source_sha256", "plan_sha256", "prompt_sha256", "model", "generation_canvas"]
  }
}
```

The final crop must be deterministic and applied before protected-pixel
restoration. `generation_placement.x/y` equals final `placement.x/y` plus
`final_crop.x/y`; guide and edit-mask scripts apply this with
`--final-crop-offset`. Stage B must use an exterior-only edit mask;
coordinates in a prompt are supporting context, never the sole constraint.

## edge_profile (required keys)

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

## fusion (required keys)

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

## atmosphere (required keys)

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

## seam (required for photo_echo)

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

## preview_review_requirements (required keys, all must be `true`)

These are pre-generation COMMITMENTS, not proof. The post-generation proof
is `final-visual-review.json`, where `fail` is a legal verdict.

- `keep_context_complete`
- `selected_shape_readable_at_thumbnail`
- `no_closed_outline`
- `no_uniform_halo`
- `no_sawtooth`
- `quiet_buffer_visible`
- `detached_transition_shapes`
- `quiet_space_supports_eye_path`
