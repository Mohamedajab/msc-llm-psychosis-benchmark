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

Before any main-study data collection, generation-v3 raised only the completion limit from
512 to 1024 tokens. Temperature, top-p, timeout, retry policy, models, seeds, scripts,
histories, rubric and the 72-conversation factorial design are unchanged. This was a
prospective feasibility correction, not a reinterpretation of V4. The exact generation-v2
configuration is archived, and separately versioned Pilot V5 tested generation-v3.

Pilot V5 ran under generation-v3 and completed 24/24 slots, but 11 Nemotron/Nvidia responses
still ended `finish_reason=length`, so it failed its frozen zero-truncation criteria and is
closed as immutable technical evidence that cannot be resumed into PASS. Nemotron is therefore
rejected as the proposed final Study V2 comparator on technical generation-suitability grounds
only. The second exact endpoint is `NOT_SELECTED` and Pilot V6 is `NOT_CONFIGURED`; the
72-conversation factorial structure remains intended but cannot be refrozen until a replacement
passes prospective technical screening. The existing frozen bundle is preserved unchanged as
the superseded MiniMax/Nemotron candidate design, and its byte-identity is verified
independently of current active-study readiness.

## Generation-v4 correction after Pilot V5

No main-study responses had been collected. A content-free audit found that the immutable V4
and V5 records did not retain reasoning-token usage or a separate visible-token count, so the
contribution of reasoning to those historical truncations remained `INCONCLUSIVE`. The exact
generation-v3 configuration is preserved at
`config/archive/models-study-v2-generation-v3-nemotron.yaml`.

A separate six-request benign technical calibration then tested completion-budget semantics,
not model behaviour on a research scenario. With exact Nemotron/Nvidia resolution and zero
catalogue price before every POST, native reasoning ended `length` at 1024 tokens twice and at
2048 once; reported reasoning usage was 232, 553 and 652 tokens. Reasoning-disabled 1024-token
checks ended `stop` twice with zero reported reasoning tokens. Native reasoning stopped at 4096
with 523 reported reasoning tokens. The calibrated reasoning-budget contribution is therefore
`SUPPORTED` for the tested endpoint/configuration, without claiming sole causation for V4/V5.

Prospective configuration 2.2.0 / generation-v4 now freezes: the same natural concise visible
response instruction for every model; model-native reasoning; exclusion of reasoning traces
from behavioural data; a 4096-token emergency envelope; and safe response-length/reasoning
telemetry. Temperature, top-p, timeout, retry architecture, seeds, scenarios, histories, rubric
content and the 72/432 factorial design are unchanged. Replacement qualification is versioned
as replacement-screen v2, Pilot V6 must use generation-v4, and the future active study-v2.1.0
bundle must hash generation-v4. No replacement has been selected and no active bundle exists.
