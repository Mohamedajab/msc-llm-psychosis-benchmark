# Research protocol — study-v2.0.0

## Questions

- RQ1: How does presentation level affect A1 belief confirmation, A2 harm enablement and
  A3 safety intervention across a six-turn exchange?
- RQ2: How do `minimax/minimax-m3:free` and
  `nvidia/nemotron-3-super-120b-a12b:free` differ on A1, A2 and A3?
- RQ3: Does standardised preloaded context change trajectories relative to no context?

## Design

Nine unchanged scripts cross three themes and three presentation levels. Each is evaluated
for two exact model endpoints, two context conditions and two seeded repetitions: 72
conversations and 432 planned responses. Execution order is seeded and frozen in the
manifest. The target receives no research, diagnostic, safety-scoring or system cue.

Generation-v2 uses temperature 0.2, top-p 1.0, maximum 512 completion tokens, a frozen
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
