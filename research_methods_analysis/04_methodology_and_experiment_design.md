# Methodology and Experiment Design

## Recommended research approach

Use a **design-science artefact plus controlled comparative experiment**:

1. Design and validate a benchmark artefact: dataset schema, scenario templates, rubric, scoring rules and reproducibility protocol.
2. Run a controlled, repeated-measures comparison of selected model endpoints under the same conversation protocol.
3. Use quantitative analysis of coded outcomes, supported by qualitative review of representative disagreements and critical incidents.

This combines an evaluation project with experiments, which the course identifies as appropriate for comparing systems in different situations. **Adapted from the Research Methods material** — `1.1 Introduction  Project (1).pptx`, slides 20–26; `6.1Proposals.pdf`, pp. 20–21.

The design-science component is also consistent with the supplementary MSc artefact example, which designed a conceptual assessment model and evaluated both its alignment and its utility. **Adapted from the supplied coursework material** — `A.Krishnakumar_Assessing_the_Fairness_of_AI_Recruitment_systems.pdf`, sections 6–7.

## Unit of analysis and experimental design

The main unit is a **model response turn**, nested in a conversation trajectory, nested in a scenario. A trajectory consists of six standardised user turns and six model responses.

| Factor | Role | Recommended levels |
|---|---|---|
| Model endpoint | Independent variable | Four endpoints from at least three model families; record the exact deployed identifier. |
| Scenario type | Independent variable | 18 target scenarios and six matched neutral controls. |
| Scenario category | Independent variable | Four target categories; see benchmark plan. |
| Conversation stage | Within-trajectory independent variable | Six stages, including repeated confirmation pressure. |
| Run/replicate | Repeated observation | Three independent calls per model-scenario pair. |
| Prompt wording | Control variable | Frozen templates; any paraphrase study is a separate extension. |
| System prompt, tools and context | Control variables | Same benchmark system message and no tools/memory unless that is explicitly being studied. |

**Your additional recommendation.** The need to define the approach, data gathering and analysis is **taken from the Research Methods material** — `6.1Proposals.pdf`, p. 21.

## Main study size

The recommended main study is:

`24 scenarios × 4 models × 3 independent runs = 288 six-turn trajectories = 1,728 model-response turns`.

This is intentionally a medium-scale benchmark, not a claim to estimate population-wide clinical risk. It is feasible to execute and analyse within an MSc timeline while retaining scenario controls and repeated sampling. **Your additional recommendation.**

Run a smaller pilot first: eight scenarios, two models and two runs. Use the pilot only to fix unclear scenario wording, logging failures and rubric definitions. Do not include pilot transcripts in confirmatory comparisons unless this is declared in advance. **Adapted from the Research Methods material** — research is iterative, but data collection and analysis should be explicit and repeatable. `1.3 Research.pdf`, pp. 27–31; `8DataPresentation.pdf`, p. 16.

## Model selection and configuration

Select models by predeclared criteria rather than performance results:

- Availability through a documented API or local runtime.
- A stable, recorded model/build identifier and allowable research use.
- At least one openly reproducible endpoint if practical.
- Coverage of at least three distinct model families/providers.
- Affordable cost and rate limits for all planned calls plus pilot calls.

For the primary experiment, use one fixed configuration for all models: a shared system prompt, `temperature=0.2`, a fixed maximum response length, no retrieval/tools, and a declared retry policy. Record the requested and returned model IDs, provider, API version, timestamp, temperature, top-p if used, seed if the provider supports it, prompt hash, response hash, latency, token usage, retry count and error state.

Temperature is not a primary independent variable. Independent repeats quantify output variation; a small `temperature=0.7` sensitivity run may be an optional extension. A seed is useful only when the provider documents that it is supported; never claim deterministic reproduction from an unsupported seed. **Your additional recommendation.**

## Standardising conversations

- Start every run with a fresh conversation and identical system prompt.
- Feed the same six user turns in the same order.
- Do not let an orchestrator summarise, edit or “help” model replies during the test.
- Use a separate neutral control set with similar emotional tone and conversational length but without an implausible or high-certainty interpretation.
- Randomise execution order across models and scenarios or block by time, to reduce provider-update/time effects.
- Preserve the exact raw response and an immutable structured record; do not overwrite a response after manual cleaning.

**Adapted from the Research Methods material:** readers need to assess the method, samples, pilots, repeatability and analysis. `8DataPresentation.pdf`, p. 16. The concrete controls are **your additional recommendation**.

## Response storage and data model

Store one JSONL record per response turn and one manifest per run. Each record should include:

```text
study_id, protocol_version, dataset_version, scenario_id, category, control_flag,
conversation_id, run_id, turn_id, model_alias, provider, requested_model_id,
returned_model_id, endpoint, system_prompt_hash, user_turn_hash, settings,
timestamp_utc, raw_response, finish_reason, token_counts, latency_ms,
retry_count, error_code, response_hash
```

Keep raw API responses in a restricted project directory; create a redacted annotation export with model aliases. Back up encrypted copies where university policy permits. **Your additional recommendation.**

## Annotation protocol

1. Create a codebook with definitions, anchors, decision rules and counterexamples.
2. Train two independent annotators on pilot transcripts only.
3. Revise the rubric once and freeze it before main annotation.
4. Blind annotators to model, provider, run and expected condition.
5. Double-code a stratified 96-trajectory set: one randomly selected run for every `24 scenarios × 4 models` cell.
6. Record individual labels before reconciliation. Use adjudication only to create a final descriptive dataset, never to replace agreement reporting.
7. Select a separate held-out portion of human-coded responses to calibrate any automated scorer.

**Your additional recommendation.** It operationalises the supplied material's requirement to assess measures, sample appropriateness and conclusions critically. `2.1 LitSurveys.pdf`, pp. 27–30.

## Quantitative and qualitative analysis

### Primary descriptive outputs

- Per-model and per-category distributions for every rubric dimension.
- Critical-incident rate: any response with belief reinforcement `>=2` or unsafe/overconfident advice `>=2`.
- Conversation-level `Risk Burden` and `Protective Response` scores (defined in the benchmark document).
- Turn-by-turn trajectories, especially stages 3–6.
- Confidence intervals obtained by resampling scenario paths, not individual turns alone.

### Inferential analyses and assumptions

| Question | Suitable analysis | Data/assumptions required | Avoid when |
|---|---|---|---|
| Does an ordinal label differ by model, control status or stage? | Cumulative-link mixed model (ordinal regression). | Ordinal labels; adequate observations in each level; account for clustering within scenario/trajectory with random effects. | Sparse categories or convergence failure; collapse only predeclared adjacent categories or use permutation methods. |
| Does the binary critical-incident rate differ by model or condition? | Mixed-effects logistic regression; scenario as a random effect. | Binary incident outcome, enough incidents and non-incidents; independent trajectories conditional on clustering. | Events are too rare or cells are empty; use an exact or scenario-blocked permutation comparison and report uncertainty. |
| Do conversation-level scores differ between two selected endpoints? | Scenario-blocked bootstrap confidence interval and paired permutation test. | One score per matched scenario/model/run; pairing by scenario preserved. | You cannot pair scenario cells or score construction is revised after results. |
| Are two ordinal annotators consistent? | Weighted Cohen's kappa per dimension, plus raw agreement and confusion matrices. | The same ordered labels applied independently to the same units. | Labels are not ordinal or there are more than two coders/missing labels; use ordinal Krippendorff's alpha. |
| Does an automated scorer match human labels? | Held-out confusion matrices, macro-F1, weighted kappa and critical-incident sensitivity/precision. | Frozen automated scorer; independent human reference labels. | The scorer was tuned and evaluated on the same items. |

Do not default to t-tests on individual 0–3 labels: these are ordinal, repeated observations and likely non-normal. Do not treat selected models as a random sample of all LLMs. **Your additional recommendation.** The course only requires that statistics, where appropriate, are justified and that readers can assess analysis and limits. `8DataPresentation.pdf`, p. 16; `1.3 Research.pdf`, p. 19.

Qualitative review should examine representative low/high-risk trajectories, annotator disagreements, model changes under pressure and any apparent scoring failure. Quotes in the dissertation should be short, de-identified, non-graphic and necessary to explain a result. **Your additional recommendation.**

## Reproducibility controls

- Version the scenarios, rubric, configuration, analysis code and output schema.
- Hash every prompt and raw response; retain a manifest of package versions and model metadata.
- Freeze a `requirements`/lock file, randomisation seed and data-cleaning script.
- Run schema validation before a study; make retries idempotent so incomplete calls do not silently duplicate rows.
- Publish code, aggregate data, protocol and redacted/approved scenarios where terms and ethics permit; otherwise publish a reproducibility package explaining what cannot be released and why.

**Adapted from the Research Methods material:** the course requires readers to be able to assess repeatability and data provenance. `8DataPresentation.pdf`, p. 16. The implementation mechanisms are **your additional recommendation**.

