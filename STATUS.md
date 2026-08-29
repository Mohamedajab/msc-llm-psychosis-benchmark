# Project status — 29 August 2026

## Current state

- Active protocol: Study V2, two models, 72 conversations, 432 response slots.
- Main-study responses collected: zero.
- Rubric: draft, pending supervisor/research-group approval.
- Pilot V4: completed 4/4 conversations and 24/24 response slots; permanently `FAIL` under
  its frozen criteria because 12 responses ended `finish_reason=length` and were truncated.
- Pilot V5: ran under generation-v3/1024 tokens; completed 4/4 conversations and 24/24
  response slots but is permanently `FAIL` because 11 responses ended `finish_reason=length`
  and were truncated. It cannot be resumed into PASS.
- Nemotron is rejected as the proposed final Study V2 comparator on technical
  generation-suitability grounds only (not clinical safety behaviour).
- MiniMax remains a technically qualified candidate based on its completed pilot behaviour.
- Replacement endpoint: `NOT_SELECTED`; Pilot V6: `NOT_CONFIGURED`.
- Main-study runner: offline by default; live Study V2 collection is blocked by
  `replacement_endpoint_not_frozen` and by the recomputed Pilot V5 `FAIL`.
- Current full offline test suite: 150 passing tests.

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

## Readiness

Pilot V4 is closed failed technical evidence. Pilot V5 is closed failed technical evidence:
it completed 24/24 response slots but 11 Nemotron/Nvidia responses were truncated, so it cannot
be resumed into PASS. Nemotron is rejected as the proposed final comparator on technical
generation-suitability grounds only. MiniMax remains technically qualified.

The second exact endpoint is `NOT_SELECTED`, Pilot V6 is `NOT_CONFIGURED`, and the main study
is `BLOCKED` by the `replacement_endpoint_not_frozen` blocker plus the recomputed Pilot V5
`FAIL`. Collection remains a no-go until a replacement endpoint passes prospective technical
screening, is explicitly frozen, and academic/rubric/ethics/data-management decisions are
genuinely approved and human annotation is ready. No main-study result exists.
