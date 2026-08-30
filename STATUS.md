# Project status — 30 August 2026

## Current state

- Active protocol: Study V2, two models, 72 conversations, 432 response slots.
- Main-study responses collected: zero.
- Rubric: draft, pending supervisor/research-group approval.
- Pilot V4: completed 4/4 conversations and 24/24 response slots; permanently `FAIL` under
  its frozen criteria because 12 responses ended `finish_reason=length` and were truncated.
- Pilot V5: ran under generation-v3/1024 tokens; completed 4/4 conversations and 24/24
  response slots but is permanently `FAIL` because 11 responses ended `finish_reason=length`
  and were truncated. It cannot be resumed into PASS.
- Nemotron failed the frozen generation-v2/v3 qualification; generation-v4 does not
  retroactively change either verdict or silently reinstate it in the primary selection.
- MiniMax demonstrated historical technical completion and remains Model A, but the final pair
  must still jointly pass Pilot V6 under generation-v4.
- Replacement endpoint: `NOT_SELECTED`; Pilot V6: `NOT_CONFIGURED`.
- Prospective generation profile: configuration 2.2.0 / generation-v4, with a shared concise
  visible-response contract, model-native reasoning, excluded reasoning traces and a 4096-token
  semantic emergency envelope with catalogue-verified per-model request-field translation and a
  120-second common timeout. Replacement screen v2 and Pilot V6 use this profile.
- Main-study runner: offline by default; live Study V2 collection is blocked by
  `replacement_endpoint_not_frozen` and by the recomputed Pilot V5 `FAIL`.
- Generation calibration: completed six benign technical requests at zero catalogue price;
  reasoning contribution `SUPPORTED`. It is not a pilot or research dataset.
- Current full offline test suite: 280 passing tests.

## Immutable technical evidence

- Pilot V1 and V2 are preserved in their original namespaces.
- Pilot V3 ran: MiniMax completed both contexts (12 responses); Gemma and GLM completed
  neither context. Aggregate Pilot V3 evidence contains 12 successful responses and eight
  HTTP 429 errors across six planned conversations.
- The one-attempt Nemotron screen returned HTTP 200 from the exact requested model through
  Nvidia, with 32 prompt tokens, 350 completion tokens, 382 total tokens, approximately
  5.409 seconds latency, and `finish_reason=length`.
- The screen proves connectivity only. It does not qualify Nemotron for the main study.
- Pilot V4 established exact endpoint/provider resolution and accessibility, but not generation
  suitability: all 12 MiniMax/GMICloud responses stopped normally, while all 12
  Nemotron/Nvidia responses reached the 512-token limit and were truncated.
- The V4/V5 budget audit found reasoning usage `NOT_REPORTED` in historical records. In the
  benign calibration, native Nemotron reached `length` at 1024 twice and 2048 once, while
  reasoning-off stopped at 1024 twice and native reasoning stopped at 4096. Reported reasoning
  tokens support a material budget contribution under those tested conditions.

## Readiness

Pilot V4 is closed failed technical evidence. Pilot V5 is closed failed technical evidence:
it completed 24/24 response slots but 11 Nemotron/Nvidia responses were truncated, so it cannot
be resumed into PASS. Nemotron failed the prospectively frozen generation-v2/v3 qualification.
MiniMax remains Model A but is not final-generation-v4 qualified until the pair passes Pilot V6.

Replacement-screen v2 is `NOT_RUN`; the second exact endpoint is `NOT_SELECTED`, Pilot V6 is
`NOT_CONFIGURED`, and the main study
is `BLOCKED` by the `replacement_endpoint_not_frozen` blocker plus the recomputed Pilot V5
`FAIL`. Collection remains a no-go until a replacement endpoint passes prospective technical
screening, is explicitly frozen, and academic/rubric/ethics/data-management decisions are
genuinely approved and human annotation is ready. No main-study result exists.
