# Generation-v4 technical calibration

Status: prospective protocol method, recorded 30 August 2026. This document contains
technical metadata only. It contains no prompt, response, reasoning trace, research rating,
or main-study result.

## Question and evidence boundary

Pilot V4 and Pilot V5 remain immutable failed technical evidence. Their stored successful
events report prompt, completion, and total tokens, but not
`completion_tokens_details.reasoning_tokens` or a separate visible-token count. Neither
pilot sent an explicit reasoning control. The content-free audit therefore records
`reasoning_contribution=INCONCLUSIVE` for the historical evidence; missing telemetry is not
interpreted as zero reasoning.

The subsequent benign calibration used a fictional community-event planning prompt, not a
research scenario. It made six generation POSTs to the exact zero-priced endpoint
`nvidia/nemotron-3-super-120b-a12b:free`. A fresh catalogue check immediately before every
POST confirmed exact identity and zero prompt/completion price. The requests used the same
temperature, top-p, seed, message structure, and 1,024-token envelope for the native versus
reasoning-disabled comparison. No response or reasoning text was printed or consulted.

| Condition | Finish | Truncated | Prompt tokens | Completion tokens | Reported reasoning tokens | Visible tokens |
|---|---:|---:|---:|---:|---:|---:|
| native reasoning, 1,024 | length | yes | 156 | 1,024 | 232 | not reported |
| reasoning disabled, 1,024 | stop | no | 156 | 882 | 0 | not reported |
| native reasoning, 1,024 repeat | length | yes | 156 | 1,024 | 553 | not reported |
| reasoning disabled, 1,024 repeat | stop | no | 156 | 835 | 0 | not reported |
| native reasoning, 2,048 | length | yes | 156 | 2,048 | 652 | not reported |
| native reasoning, 4,096 | stop | no | 156 | 1,813 | 523 | not reported |

Interpretation: **SUPPORTED**. Under the tested endpoint and benign request, reasoning-token
allocation materially contributed to completion-budget exhaustion. This does not prove that
reasoning was the sole cause of Pilot V4/V5 truncation, and it does not inspect or rescue any
substantive model behaviour.

## Authoritative technical provenance

Sources were accessed on 30 August 2026.

- [OpenRouter reasoning tokens](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens):
  reasoning tokens are output tokens; the unified `reasoning` object supports effort,
  budget, enablement, and exclusion; `exclude` removes the trace but does not disable
  reasoning; per-model catalogue metadata reports whether reasoning is mandatory and which
  controls are supported.
- [OpenRouter chat-completion API](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion):
  `max_completion_tokens` is the preferred maximum-completion field; `max_tokens` remains a
  documented deprecated compatibility field. Generation-v4 freezes a provider-independent
  4,096-token envelope; retained exact catalogue evidence selects the supported field for each
  model, and that translation is stored and hashed before generation.
- [OpenRouter usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting):
  reasoning usage is reported, where available, at
  `usage.completion_tokens_details.reasoning_tokens`; cached prompt tokens may be reported at
  `usage.prompt_tokens_details.cached_tokens`.
- [OpenRouter provider routing](https://openrouter.ai/docs/guides/routing/provider-selection):
  `allow_fallbacks=false` disables fallback and `require_parameters=true` restricts routing
  to providers supporting supplied parameters.
- [OpenRouter Nemotron free endpoint](https://openrouter.ai/nvidia/nemotron-3-super-120b-a12b%3Afree):
  exact endpoint identity, free pricing, text modality, context, and reasoning capability.
- [NVIDIA Nemotron 3 Super model card](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/modelcard):
  reasoning defaults on, may be disabled in NVIDIA's native chat template, and shares the
  overall output allowance with the visible response in the documented budgeted workflow.

The live exact catalogue entry reported: prompt price 0, completion price 0, text input and
output, seed and reasoning support, 262,144-token context, reasoning optional and enabled by
default, supported efforts `medium` and `low`, and reasoning-budget support. This calibration
catalogue metadata is not governed replacement-catalogue evidence and cannot advance
replacement selection.

## Frozen generation-v4 profile

- visible-response instruction: disabled (`null`); no additional concision, style, sentence,
  word or response-length intervention is inserted into the target conversation;
- completion envelope: 4,096 tokens, a prospectively validated non-binding emergency ceiling
  for the intended MiniMax/Nemotron comparison rather than a desired response length or a
  universal fairness rule;
- common timeout: 120 seconds, reducing avoidable censoring while latency remains technical
  telemetry rather than a standalone admission outcome;
- reasoning: model-native, with the reasoning trace excluded from returned behavioural text;
- telemetry: visible characters, words and sentences; reported prompt, completion, reasoning,
  visible and cached tokens; finish reason; truncation; latency; requested/resolved model;
  provider; and reasoning-control metadata;
- unavailable usage classes remain null and are never inferred.

The benchmark standardises stimuli, conversation structure, conditions, repetitions and
outcome measurement. It does not require heterogeneous models to expose identical tokenisers,
hidden reasoning allocation or API fields. Model-native reasoning is retained because the
reusable benchmark must not require every family to expose an equivalent reasoning-off
control. The MSc matched study still admits the intended original pair only if Pilot V6
completes every turn with `finish_reason=stop` and zero truncation under generation-v4.

## Scope

Truncation remains a reportable technical benchmark outcome. It is not a substantive rubric
score and does not make a model intrinsically unbenchmarkable. For the MSc multi-turn matched
study, truncation remains a strict admission failure because an incomplete assistant turn can
affect all later turns. A newly truncated trajectory is persisted through that exact turn and
then closed; resume cannot generate downstream turns. Pilot V6 later passed generation-v4
qualification with 24/24 `stop` responses and zero truncation. No main-study data exist, the
replacement screen remains NOT_RUN, the active bundle remains NOT_CREATED, and the main study
remains BLOCKED.
