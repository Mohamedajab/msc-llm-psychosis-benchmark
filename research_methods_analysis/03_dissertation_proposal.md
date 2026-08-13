# Dissertation Proposal: Multi-Turn Chatbot Safety Benchmark

## Recommended title

1. **A Reproducible Multi-Turn Safety Benchmark for Evaluating Epistemic Reinforcement in Large-Language-Model Chatbots** — **recommended**.
2. **Beyond Single-Turn Safety: Measuring Risk Trajectories in Synthetic Conversations with Language-Model Chatbots**.
3. **Evaluating Support, Uncertainty and Reinforcement in Multi-Turn AI Chatbot Conversations**.

The first title is strongest because it states the artefact (benchmark), technical setting (multi-turn language-model chatbots) and evaluated behaviour (epistemic reinforcement) without making an untestable clinical-causation claim. **Your additional recommendation.**

## Problem statement

Chatbots can respond warmly and fluently to users describing uncertainty or strongly held interpretations. In this context, a response can be emotionally validating without endorsing an unverified interpretation; conversely, excessive agreement, certainty, escalation, dependency cues or overconfident advice may be unsafe. Existing generic benchmarks often assess a single prompt, so they may miss whether a model maintains appropriate boundaries when a conversation continues and the user requests confirmation repeatedly.

The problem is therefore not to diagnose a person or prove that a model causes a clinical condition. It is to create a controlled, repeatable way to measure a defined set of chatbot response behaviours in safe synthetic multi-turn scenarios. **Your additional recommendation.**

This scope follows the course view that computing development needs critical evaluation and experiments can compare systems in different situations. **Adapted from the Research Methods material** — `1.1 Introduction  Project (1).pptx`, slides 22–23.

## Overall aim

To design, implement and validate a reproducible benchmark and Python evaluation pipeline for measuring selected language-model chatbots' safety response trajectories in safe synthetic multi-turn conversations involving uncertainty, pressure for confirmation and dependence-related cues.

**Adapted from the Research Methods material:** the aim is singular, outcome-oriented and supported by measurable objectives, as required for a proposal. `6.1Proposals.pdf`, pp. 13–21; `week 89  ProjectMgmt.pptx`, slides 9–14.

## Research questions

| Research question | Evidence and measure that answers it |
|---|---|
| **RQ1.** Does the benchmark distinguish targeted scenarios from matched neutral controls in risk burden and critical-incident rate? | Human-coded `Risk Burden`, critical incidents, and protective-response profile by scenario type. |
| **RQ2.** How do selected model endpoints differ in harmful and protective response profiles under an identical multi-turn protocol? | Model-level distributions, scenario-blocked comparisons and confidence intervals. |
| **RQ3.** How do response profiles change across conversation stages, especially after repeated requests for confirmation? | Turn/stage effects and trajectory plots from the coded data. |
| **RQ4.** Can the annotation rubric be applied reliably by independent annotators, and can an automated scorer be calibrated against those labels? | Weighted agreement/ordinal agreement, disagreement analysis and held-out calibration performance. |

**Adapted from the Research Methods material:** the questions separate observable outcomes from the methods used to measure them, reflecting the course expectation that research questions, samples, data gathering and analysis are explicit. `6.1Proposals.pdf`, pp. 18–21; `2.1 LitSurveys.pdf`, pp. 27–30.

## Testable expectations

These are study expectations, not claims to be assumed true:

- **H1:** target scenarios will have a higher rate of coded risk than matched neutral controls.
- **H2:** repeated pressure for confirmation will increase risk for at least some model endpoints or scenario categories.
- **H3:** selected model endpoints will differ in risk burden and protective response profile.
- **H4:** automated scoring will be less reliable than independent human coding for nuanced distinctions such as emotional validation without belief endorsement.

**Your additional recommendation.** The pilot may show that some hypotheses need removal or reformulation before the main protocol is locked.

## Objectives

1. Conduct a documented, critical literature review covering chatbot safety, psychosis-related conversational risks, sycophancy, multi-turn evaluation, benchmark design, annotation and safeguards.
2. Turn the literature review and supervisor feedback into operational definitions of reinforcement, emotional validation, grounding, escalation, dependency-forming language and unsafe advice.
3. Create a versioned, safe synthetic dataset of 24 six-turn scenario paths: 18 target paths across four categories and six matched neutral controls.
4. Specify and pilot a blinded ordinal annotation rubric and codebook.
5. Implement a Python pipeline that executes standardised conversations, records complete metadata and handles API failures/retries.
6. Run a pilot, revise the artefact once, then freeze the main-study protocol and dataset version.
7. Evaluate four selected model endpoints with three independent runs per scenario, producing 288 conversation trajectories.
8. Double-code a stratified sample of 96 trajectories, calculate annotation reliability, and investigate disagreements.
9. Analyse model, scenario-type and stage effects using methods appropriate to ordinal/clustered data; generate auditable tables and visualisations.
10. Critically evaluate validity, reproducibility, ethics, technical limitations and the benchmark's future use.

Objectives 3–9 are **your additional recommendation**. The objective structure and explicit deliverables are **adapted from the Research Methods material** — `6.1Proposals.pdf`, pp. 13–21; `week 89  ProjectMgmt.pptx`, slides 6–17.

## Is this suitable for an MSc Advanced Computer Science dissertation?

Yes—provided that the dissertation is framed as a **benchmark and evaluation-systems contribution**, rather than as an API comparison or a claim of psychiatric efficacy/harm. The course explicitly identifies evaluation projects and problem-solving projects as valid computing project types, while saying that development requires evaluation at postgraduate level. **Taken from the Research Methods material** — `1.1 Introduction  Project (1).pptx`, slides 20–26.

### The required technical contribution

The project must contain all of the following:

- A versioned benchmark schema, safe conversation state machine and scenario validator.
- A provider-agnostic experiment runner that can replay model experiments from configuration.
- An auditable annotation/scoring system that distinguishes belief endorsement from emotion validation.
- Reproducible analysis code, provenance metadata, quality checks and visual reporting.
- A validation argument: pilot results, annotation reliability, matched controls and threats to validity.

**Your additional recommendation.** These elements make the work a reusable evaluation artefact rather than a collection of responses.

## What would make the project weak or fail?

- Calling several APIs and ranking the answers without an explicit construct, rubric, controls or reliability check.
- Using real people, patient records or user-generated crisis content without a separate approved protocol.
- Defining "safe" as merely refusing a prompt, thereby incorrectly penalising appropriate emotional empathy.
- Making causal clinical claims from synthetic transcripts.
- Changing prompts, model configurations or scoring rules after inspecting results without a versioned record.
- Overloading the scope with too many models, a dashboard, fine-tuning and a large human study at the same time.

The need for a defined outcome, risk plan, methodology, evaluation and limits on claims is **taken from/adapted from the Research Methods material** — `6.1Proposals.pdf`, pp. 9–27; `1.3 Research.pdf`, pp. 19 and 37–38. The concrete failure modes are **your additional recommendation**.

## Minimum viable project and high-grade extension

| Level | Deliverable |
|---|---|
| **Minimum viable project** | 12 scenarios (eight target, four controls), three model endpoints, two runs, six turns, pilot-tested rubric, 72 trajectories, two-rater coding of a balanced subset, reproducible pipeline and critical analysis. |
| **Recommended dissertation scope** | 24 scenarios, four model endpoints, three runs, 288 trajectories, 96 double-coded trajectories, calibrated automated scorer, model/stage/control analysis and publication-quality figures. |
| **Optional extension** | Paraphrase robustness study, secure lightweight annotation interface, one local open-weight model, containerised replay, or a separate LLM-as-judge sensitivity analysis. |

**Your additional recommendation.** Do not start optional work until the recommended core has a frozen pilot protocol and successful end-to-end run.

## Recommended dissertation chapter structure

The course provides an experimental structure of Introduction, Background/Literature Review, Problem Statement/Hypothesis, Methods, Experiments/Data Gathering, Results, Conclusions, References and Appendices. **Taken from the Research Methods material** — `3.1 WritingReports.pdf`, p. 5.

The following is an **example allocation for a 15,000-word dissertation**. The supplied material does not state the actual word limit, so confirm it in the current handbook and scale the percentages, not the evidence depth. **Your additional recommendation.**

| Chapter | Main content | Example words | Share |
|---|---|---:|---:|
| 1. Introduction | Problem, scope boundary, aim, RQs, contributions and roadmap. | 1,500 | 10% |
| 2. Literature Review | Thematic critical review, gap and method justification. | 3,000 | 20% |
| 3. Benchmark Requirements and Design | Construct definitions, scenario schema, controls, rubric and safety requirements. | 2,200 | 15% |
| 4. Methodology | Design-science/experiment design, models, annotation, statistics and ethics. | 2,200 | 15% |
| 5. Technical Implementation | Architecture, data model, reproducibility, tests and runner. | 2,400 | 16% |
| 6. Results | Dataset completion, reliability, descriptive and comparative findings. | 2,000 | 13% |
| 7. Critical Evaluation | Validity, limitations, failure cases, ethical implications and future work. | 1,200 | 8% |
| 8. Conclusion | Answers to RQs and concise contribution statement. | 500 | 3% |
| References and appendices | Search log, codebook, schema, configuration and extended tables. | Excluded unless handbook says otherwise | — |

Writing should proceed alongside implementation; write the abstract after the report is complete and ensure the conclusion states how objectives were met, contribution, limitations and future work. **Taken from the Research Methods material** — `3.1 WritingReports.pdf`, pp. 2–3, 29–36 and 40–42.
