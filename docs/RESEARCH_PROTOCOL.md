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
conversations and 432 planned responses. Execution order is seeded and frozen in the
manifest. The target receives no research, diagnostic, safety-scoring or system cue.

Generation-v3 uses temperature 0.2, top-p 1.0, maximum 1024 completion tokens, a frozen
repetition seed and a 45-second timeout. Exact catalogue qualification occurs immediately
before live use. Provider routing follows `PROVIDER_POLICY.md`.

## Outcomes and analysis

A1, A2 and A3 are separate primary ordinal outcomes. B1, B2, B3 and C1 remain separate and
exploratory; no seven-axis total is permitted. Human annotation is primary. Analyses use
conversation summaries, onset/persistence/recovery, matched model/context comparisons and
whole-conversation or whole-script-cluster bootstrap. Turns are not independent units.

A textual response ending because of `finish_reason=length` is retained as observed and
flagged `truncated`. Its frequency is reported and a sensitivity analysis excludes such
observations. Missing responses and technical errors are never imputed.

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

Before any live Study V2 execution, a technically suitable replacement endpoint must be
screened prospectively and frozen; until then the `replacement_endpoint_not_frozen` blocker
keeps the main study `BLOCKED`. Any future endpoint qualification requires the exact frozen
cells, six contiguous successful turns per cell, exact requested/resolved model identity,
non-empty private response text, reported provider and finish reason, zero truncations, and
only complete finish reasons, with no more than the prespecified attempt cap. Malformed,
mixed-version, duplicated, non-contiguous, stale or unverifiable evidence fails closed.
Transient errors may remain append-only if all slots later succeed within the cap and reveal
no integrity mismatch. This technical gate is separate from human supervisor, rubric,
annotation, ethics and data-management approval.
