# Intake Contract

Use one compact question round before planning. Ask only fields that cannot
be derived from the source or environment; apply the defaults below when the
user does not specify a value.

## Ask

1. Final use and canvas size (default: preserve source dimensions).
2. Protected subject or region (default: the visually isolated primary
   subject; confirm whether surrounding contact shadow belongs to it).
3. Visual direction (default: quiet editorial collage with source-led colors).
4. Context to keep or discard (default: discard the original rectangular
   background, keep only source pixels inside the protected mask).
5. Exact text, logos, or exclusions (default: no generated text, logos, or
   watermark removal).

Do not ask for source dimensions, alpha state, model-supported generation
sizes, or certificate state: inspect those automatically. If a watermark
crosses the protected region, state that it will be preserved and request an
authorized clean source when removal is desired.

## Before generation

Write the resolved answers to `creative-brief.json`. Show the user one mask
preview when the boundary is ambiguous. Do not spend a generation request on
an unapproved mask, unsupported canvas mapping, missing credential, or failed
TLS/provider preflight.

## Generation budget

Default to one Stage A request and at most two Stage B requests. Cache each
accepted stage by source hash, plan hash, prompt hash, model, and generation
canvas. Transport/TLS failures do not consume a generation attempt. A Stage B
failure must reuse the accepted Stage A output and regenerate only the
transition layer. Never regenerate a verified protected subject.
