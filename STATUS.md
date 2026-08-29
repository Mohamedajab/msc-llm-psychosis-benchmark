# Project status — 29 August 2026

## Current state

- Active protocol: Study V2, two models, 72 conversations, 432 response slots.
- Main-study responses collected: zero.
- Rubric: draft, pending supervisor/research-group approval.
- Pilot V4: implemented/planned, not executed.
- Main-study runner: offline by default; no live Study V2 execution has occurred.
- Pilot V4 qualification gate: implemented; current verdict `NOT_RUN` because no V4 raw
  evidence exists. The assessor exits non-zero and Study V2 live collection remains blocked.
- Current full offline test suite: 127 passing tests.

## Immutable technical evidence

- Pilot V1 and V2 are preserved in their original namespaces.
- Pilot V3 ran: MiniMax completed both contexts (12 responses); Gemma and GLM completed
  neither context. Aggregate Pilot V3 evidence contains 12 successful responses and eight
  HTTP 429 errors across six planned conversations.
- The one-attempt Nemotron screen returned HTTP 200 from the exact requested model through
  Nvidia, with 32 prompt tokens, 350 completion tokens, 382 total tokens, approximately
  5.409 seconds latency, and `finish_reason=length`.
- The screen proves connectivity only. It does not qualify Nemotron for the main study.

## Readiness

Pilot V4 remains a conditional go after separate live authorisation. Completion alone is not
enough: the versioned assessor must independently return PASS with 24/24 complete,
non-truncated slots and all frozen integrity criteria satisfied within 32 HTTP attempts. The
main study is a no-go until that machine gate passes, academic/rubric/ethics/data-management
decisions are genuinely approved, and human annotation is ready.
