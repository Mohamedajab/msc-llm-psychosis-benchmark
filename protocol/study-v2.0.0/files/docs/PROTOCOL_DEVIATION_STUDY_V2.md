# Pre-main-study protocol revision: Study V2

Status: adopted before main-study data collection on 29 August 2026.

The original Study V1 plan crossed three presentation levels, three themes, three target
models, two context conditions and two repetitions: 108 conversations and 648 planned
responses. No main-study responses were collected under that design.

Study V2 removes the technically unreliable Gemma/GLM candidates and retains MiniMax M3
plus NVIDIA Nemotron Super. The revised design is 3 × 3 × 2 × 2 × 2 = 72 conversations,
with 432 planned response observations. This preserves every psychological manipulation,
both context conditions, two frozen repetitions and the complete six-turn trajectory.

The revision is justified by free-endpoint feasibility, Pilot V1-V3 reliability evidence,
the annotation workload, and the roadmap's priority on a complete auditable MSc study.
MiniMax completed technical conversations. Nemotron demonstrated connectivity in one
technical screen but exhausted the prior 350-token limit; it remains provisional until
Pilot V4. The generation-v2 limit is therefore frozen at 512 tokens before results exist.

Pilot and screen observations are engineering evidence, not dissertation results. The
draft rubric still requires supervisor/research-group approval before primary annotation.

Governance clarification (pre-collection): four completed Pilot V4 conversations do not by
themselves qualify the endpoints. A versioned, deterministic assessor must return PASS from
the immutable V4 records. In particular, a length-limited or otherwise incomplete finish is
retained as technical evidence but disqualifies Pilot V4. That V4 gate was frozen before its
execution and is retained for historical interpretation. This clarification changed no model,
scenario, history, seed,
generation parameter, manifest row or factorial-design decision.

## Generation-v3 correction after Pilot V4

Pilot V4 subsequently tested generation-v2 at 512 completion tokens. It completed 24/24
technical response slots with exact model resolution and no transport errors, but 12/24
responses—all from the Nemotron endpoint through Nvidia—ended `finish_reason=length` and
were truncated. MiniMax through GMICloud produced 12/12 `stop` responses. Pilot V4 therefore
remains permanently `FAIL` under its frozen prospective criteria.

Before any main-study data collection, generation-v3 raises only the completion limit from
512 to 1024 tokens. Temperature, top-p, timeout, retry policy, models, seeds, scripts,
histories, rubric and the 72-conversation factorial design are unchanged. This is a
prospective feasibility correction, not a reinterpretation of V4. The exact generation-v2
configuration is archived, and separately versioned Pilot V5 must qualify generation-v3.
