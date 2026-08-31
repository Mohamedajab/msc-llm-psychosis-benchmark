# Technical evaluation-framework precedent

Status: technical methodology source notes, not literature-review prose. Sources were
accessed on 30 August 2026.

## Protocol principle

The benchmark standardises experimental stimuli, conversation structure, conditions and
evaluation outcomes. Provider- and model-specific generation parameters may differ where
required to express an equivalent evaluation configuration across heterogeneous APIs.

The evaluated unit is therefore a frozen deployed-chatbot configuration. Any later claim
must be framed as applying **under the frozen evaluation configuration**, not as a universal
property of a model family.

## Implementation observations

### Inspect AI

- Sources: [Using Models](https://inspect.aisi.org.uk/models.html),
  [Reasoning](https://inspect.aisi.org.uk/reasoning.html), and
  [Model APIs](https://inspect.aisi.org.uk/extensions-model-api.html).
- Observation: Inspect separates task execution from provider implementations, permits
  per-model generation configuration and provider arguments, maps reasoning controls across
  provider APIs, records reasoning separately from visible text, and allows a model API to
  define its own default maximum generation.
- Protocol inference: task invariants should be frozen independently from provider-appropriate
  parameter translation. This supports the existing semantic-envelope/actual-field split; it
  does not require migrating this repository to Inspect AI.

### DelusionEval

- Sources: [project repository](https://github.com/jlcmoore/llm-delusion-eval) and
  [extended reference](https://github.com/jlcmoore/llm-delusion-eval/blob/main/EXTENDED_REFERENCE.md).
- Observation: DelusionEval uses Inspect AI, documents provider-appropriate reasoning
  controls, says to omit a control when a model does not expose it, and supports offline mock
  execution. Generation limits remain configurable through Inspect rather than being treated
  as a single universal model property.
- Protocol inference: a mental-health-related evaluation can preserve matched task inputs
  while allowing provider-appropriate reasoning semantics and explicit technical logging.

### Spiral-Bench

- Sources: [project repository](https://github.com/sam-paech/spiral-bench) and
  [API client](https://github.com/sam-paech/spiral-bench/blob/main/api_client.py).
- Observation: the client translates generation settings by model family, including
  `max_tokens` versus `max_completion_tokens`, larger allowances for some reasoning models,
  model-specific reasoning settings, a 120-second request timeout, and explicit detection of
  `finish_reason=length`.
- Protocol inference: standardising the behavioural task does not imply identical low-level
  request fields or hidden reasoning mechanics. The implementation is precedent, not a
  template to copy wholesale.

### Psychosis-Bench

- Sources: [project repository](https://github.com/w-is-h/psychosis-bench) and its
  [package source](https://github.com/w-is-h/psychosis-bench/tree/main/psy_bench).
- Observation: the project executes structured multi-turn cases through OpenRouter with a
  comparatively lightweight provider layer. Its public interface chooses model identity and
  turn range without presenting one universal fixed token allowance as the scientific
  construct.
- Protocol inference: exact request auditing in this repository should remain stronger, while
  generation mechanics stay subordinate to the frozen experimental task.

## Scope boundary

These notes record software-design precedent only. They do not constitute the student's
critical literature synthesis, validate this project's rubric, establish clinical validity,
or report research findings.
