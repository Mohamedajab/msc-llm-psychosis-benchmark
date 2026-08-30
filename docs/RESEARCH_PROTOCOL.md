# Research protocol — study-v2.0.0

## Questions

- RQ1: How does presentation level affect A1 belief confirmation, A2 harm enablement and
  A3 safety intervention across a six-turn exchange?
- RQ2: How does `minimax/minimax-m3:free` differ from a second, technically governed exact
  endpoint (pending replacement selection after Nemotron was rejected on technical
  generation-suitability grounds only) on A1, A2 and A3?
- RQ3: Does standardised preloaded context change trajectories relative to no context?

## Design

Nine unchanged scripts cross three themes and three presentation levels. Each is evaluated
for two exact model endpoints, two context conditions and two seeded repetitions: 72
conversations and 432 planned responses. Execution order will be seeded and frozen in the
final manifest after replacement selection. The target receives no research, diagnostic or
safety-scoring cue. Generation-v4 adds one identical, neutral visible-response system
instruction to every target request.

Generation-v4 uses temperature 0.2, top-p 1.0, a 4096-token emergency completion envelope,
the frozen repetition seed and a 45-second timeout. The envelope is not a target length.
The shared visible-response contract asks for a natural, direct, concise but complete answer.
Reasoning remains model-native because equivalent off-controls cannot be assumed across model
families; reasoning traces are excluded and never become behavioural data. Exact catalogue
qualification occurs immediately before live use. Provider routing follows
`PROVIDER_POLICY.md`.

## Outcomes and analysis

A1, A2 and A3 are separate primary ordinal outcomes. B1, B2, B3 and C1 remain separate and
exploratory; no seven-axis total is permitted. Human annotation is primary. Analyses use
conversation summaries, onset/persistence/recovery, matched model/context comparisons and
whole-conversation or whole-script-cluster bootstrap. Turns are not independent units.

A textual response ending because of `finish_reason=length` is retained as observed and
flagged `truncated`. Its frequency is reported and a sensitivity analysis excludes such
observations. It remains a technical benchmark outcome rather than a substantive complete
answer. Missing responses and technical errors are never imputed. Visible-length, usage,
reasoning-reporting coverage and latency are reported separately from rubric outcomes.

## Status and boundaries

The rubric is draft and awaiting academic approval. No main-study result exists. Pilot and
screen evidence is feasibility evidence only. The historical Study V1 design and reasons
for revision are preserved in `PROTOCOL_DEVIATION_STUDY_V2.md`.

Pilot V4 tested archived generation-v2 at 512 tokens. It completed all slots but failed its
prospectively frozen zero-truncation rule: 12/24 responses ended `length`. The records remain
immutable technical evidence and cannot be resumed into PASS.

Pilot V5 ran under generation-v3 at 1024 tokens. It completed 24/24 slots but 11 responses
ended `length`, so `pilot-v5-qualification-v1.0.0` recomputes `FAIL` with failed criteria
`zero_truncated_responses` and `only_complete_finish_reasons`. Successful turns are immutable,
so Pilot V5 cannot be resumed into PASS. Nemotron is therefore rejected as the proposed final
Study V2 comparator on technical generation-suitability grounds only; this is not a claim about
Nemotron's clinical or psychosis-related safety behaviour. MiniMax remains technically
qualified based on its completed pilot behaviour.

The stored V4/V5 records do not report reasoning-token usage, so their causal interpretation
remains inconclusive. A separate benign generation calibration, not research data, found that
native reasoning materially contributed to budget exhaustion under the tested Nemotron route:
two native 1024-token checks and one native 2048-token check ended `length`, while two
reasoning-disabled 1024-token checks and one native 4096-token check ended `stop`. Generation-v4
was prospectively frozen from that technical evidence before any main-study collection. The
historical Pilot V5 verdict remains `FAIL`.

Before any live Study V2 execution, a technically suitable replacement endpoint must pass
replacement-screen v2 under generation-v4 and be frozen; until then the
`replacement_endpoint_not_frozen` blocker
keeps the main study `BLOCKED`. Any future endpoint qualification requires the exact frozen
cells, six contiguous successful turns per cell, exact requested/resolved model identity,
non-empty private response text, reported provider and finish reason, zero truncations, and
only complete finish reasons, with no more than the prespecified attempt cap. Malformed,
mixed-version, duplicated, non-contiguous, stale or unverifiable evidence fails closed.
Transient errors may remain append-only if all slots later succeed within the cap and reveal
no integrity mismatch. This technical gate is separate from human supervisor, rubric,
annotation, ethics and data-management approval.
