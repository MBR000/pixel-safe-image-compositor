# Mask geometry gates per mode

Read this before building the mask. Preflight enforces every gate with
exit code 1.

## subject_cutout and organic_context

For these two modes the mask edge MUST obey all of the following:

Choose a shape language from the plan's `design_intent`: `motion_brush`,
`leaf_sweep`, `wedge_sweep`, `counterform`, or `contour_echo`. Geometry
safety is necessary but not sufficient: a centered oval or evenly padded
photo island can pass numeric gates while still reading as an un-designed
container. The mask should have a leading mass and a trailing taper that
agree with the subject's gesture or the declared eye path.

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
- At thumbnail size, the protected shape must communicate directional
  asymmetry. If the subject is static, use a deliberate counterform or
  contour echo and document the negative-space role instead of defaulting to
  a centered pebble or oval.
- Integration is a separate gate: no visible rectangular or rounded
  cover-up panel may sit in the quiet field, no large uniform wash may erase
  a generation error, and the seam must carry at least one shared material,
  color, or contour cue across both sides.

## photo_window

A rectangular window is allowed ONLY when the plan explicitly declares:

```json
{ "mode": "photo_window", "window": { "type": "rectangle_mask" } }
```

Without both declarations, a rectangular mask is rejected by preflight.
Conversely, a `photo_window` plan requires a near-rectangular mask
(rectangularity >= 0.98); declaring `photo_window` with an organic mask is
also rejected.

## photo_echo

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
