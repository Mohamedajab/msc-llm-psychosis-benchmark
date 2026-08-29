# Project status — 29 August 2026

## Current state

- Active protocol: Study V2, two models, 72 conversations, 432 response slots.
- Main-study responses collected: zero.
- Rubric: draft, pending supervisor/research-group approval.
- Pilot V4: completed 4/4 conversations and 24/24 response slots; permanently `FAIL` under
  its frozen criteria because 12 responses ended `finish_reason=length` and were truncated.
- Pilot V5: implemented/planned under generation-v3, not executed; current verdict `NOT_RUN`.
- Main-study runner: offline by default; no live Study V2 execution has occurred.
- Main-study machine gate: Pilot V5 PASS required; current live collection state is blocked.
- Current full offline test suite: 139 passing tests.

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

Pilot V4 is closed failed technical evidence. Pilot V5 is a conditional go only after separate
live authorisation. The main study is a no-go until Pilot V5 independently passes with 24/24
complete, non-truncated slots within 32 attempts, academic/rubric/ethics/data-management
decisions are genuinely approved, and human annotation is ready. No main-study result exists.
