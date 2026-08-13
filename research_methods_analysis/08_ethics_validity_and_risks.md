# Ethics, Validity, Risks and Critical Evaluation

## Ethical position

This is a non-clinical benchmark study. It must not claim to diagnose, treat or predict psychosis, and it must not ask people experiencing distress to use chatbots as part of the study. The main experiment uses synthetic, low-detail scenarios and model outputs only. **Your additional recommendation.**

This cautious, proportionate approach is consistent with the course's requirements to identify project risks, contingency plans and limitations, and to use information ethically. **Adapted from the Research Methods material** — `6.1Proposals.pdf`, pp. 13 and 18–27; `COP500_Research methods_C Greasley_2025.pptx`, slides 37–60.

## Ethics and safeguarding risk register

| Risk | Why it matters | Mitigation | Residual decision |
|---|---|---|---|
| Sensitive mental-health-adjacent content | Scenario wording or outputs may be distressing. | Use non-graphic synthetic templates, exposure limits, content warning, pause/opt-out and supervisor escalation route. | Seek ethics/safeguarding confirmation before pilot. |
| Harmful model outputs | The system may generate reinforcement, escalation or unsafe advice. | Run in controlled accounts; never send outputs to real users; restrict raw transcripts; stop and report any unexpectedly severe output. | Acceptable only with risk protocol. |
| Researcher/annotator exposure | Repeated reading can cause distress or fatigue. | Train raters, cap sessions, offer breaks/withdrawal, avoid high-risk details, use a distress/escalation protocol and debrief. | Ethics approval may be required for annotators. |
| Real patient or user data | Privacy, consent and data-protection risk. | Do not collect, scrape, adapt or store real chat logs or health records. | Out of scope. |
| Human participants | Participation could create clinical or safeguarding obligations. | Main study has none. Any clinician/expert review or annotator study requires an approved protocol first. | Supervisor/ethics decision required. |
| Privacy of API outputs | Prompts/responses and provider logs may be retained. | Use synthetic prompts, minimum data, access control, encrypted storage where available, documented retention/deletion and provider-terms review. | Check provider terms before collection. |
| Benchmark misuse | Exact prompts might be used to probe or bypass safeguards. | Release schemas/categories and approved redactions; assess prompt release separately; include responsible-use statement. | Do not open-release unreviewed high-risk text. |
| Misleading safety claims | A model may appear safe on a narrow synthetic test but fail elsewhere. | State scope prominently, use controls and limitations, avoid clinical claims, publish configuration. | Always report as benchmark-specific. |
| Model-provider terms | APIs may restrict storage, redistribution or safety testing. | Document provider, terms date, endpoint and allowed use; do not publish raw outputs unless permitted. | Block model if terms conflict. |

**Your additional recommendation.** The WHO's 2024 guidance is an external verified source supporting attention to governance, stakeholders, well-defined tasks and risk assessment; it is not course material. https://www.who.int/publications/b/70584

## Ethics approval decision tree

1. **Synthetic model-only pilot:** ask the supervisor whether a formal ethics self-assessment is still needed; do not assume exemption.
2. **Independent annotators:** obtain the institution's decision before recruiting, briefing or paying anyone.
3. **Clinical advisers, people with lived experience or user testing:** require formal ethical review and a safeguarding plan before contact.
4. **Real transcripts or health-related data:** out of scope unless the project is redesigned under a full data-governance and ethics protocol.

**Your additional recommendation.**

## Validity and reliability threats

| Threat | Risk to the study | Realistic mitigation |
|---|---|---|
| Construct validity | “Reinforcement” may be confused with empathy, politeness or summarisation. | Separate belief reinforcement from emotional validation; use decision rules, counterexamples and expert/supervisor review. |
| Internal validity | Model differences may actually be caused by prompts, settings, dates or tools. | Freeze prompts/system settings, block execution, record versions, use controls and fresh conversations. |
| External validity | Four endpoints and 24 synthetic scenarios cannot represent all chatbots or users. | Limit claims to selected endpoints/configurations; include model families and scenario categories, not claims about all AI. |
| Ecological validity | Synthetic conversations lack the history, emotional context and autonomy of real users. | Describe the artefact as a controlled stress test, not a simulation of lived experience. |
| Sampling bias | Scenario authors may encode one cultural interpretation of “safe.” | Use diverse neutral phrasing, reviewer feedback, rationale records and optional future co-design. |
| Prompt sensitivity | Small wording changes can change model behaviour. | Lock templates; make paraphrase sensitivity a separate, clearly labelled extension. |
| Model-version instability | Provider updates invalidate exact replication. | Store requested/returned identifiers, timestamps and raw outputs; rerun a fixed sentinel subset later. |
| Annotation reliability | Raters may disagree on nuance. | Pilot calibration, blinded double coding, agreement statistics and disagreement analysis. |
| Automated-judge bias | A judge can prefer verbosity, its own family or a particular response order. | Human labels are the reference; calibrate/evaluate on held-out data and swap order in pairwise tests. |
| Composite-score validity | Arbitrary weights can hide a serious unsafe response. | Publish dimension-level results first; make critical incidents a non-compensatory safety gate; sensitivity-test weights. |
| Statistical conclusion validity | Small/rare outcomes can produce unstable p-values or failed models. | Emphasise effect sizes and scenario-blocked confidence intervals; use exact/permutation alternatives; report sparse cells. |

The requirement to evaluate measures, design, sample, statistical techniques, conclusions and limitations is **taken from the Research Methods material** — `2.1 LitSurveys.pdf`, pp. 25–32. The application to this benchmark is **adapted from the Research Methods material / your additional recommendation**.

## Reproducibility and auditability

The source material says researchers should report data collection, sample selection, pilots and analysis so readers can assess validity and repeatability. **Taken from the Research Methods material** — `8DataPresentation.pdf`, p. 16.

Apply that principle by maintaining:

- a protocol version and change log;
- a scenario/rubric version and review status;
- immutable raw response records and hashes;
- full model/configuration manifests;
- deterministic analysis scripts and locked dependencies;
- a missing-data/error log;
- a reproducibility package containing permitted data, code, figures and known restrictions.

**Adapted from the Research Methods material.**

## Strict supervisor critique

### What is still too vague

- “Reinforce”, “validate”, “amplify” and “psychosis-related patterns” need operational definitions before data collection.
- “Multiple models” needs a predeclared number and selection rule.
- “Safe response” must not equate to a refusal; it needs a positive account of empathetic uncertainty and grounded support.
- “Validation” needs a defined target: content review, annotation reliability, control discrimination and/or automated-score calibration.

### What is too ambitious

- A large scenario bank, many model providers, extensive human participants, expert interviews, a dashboard, model fine-tuning and publication-quality study cannot all be core MSc deliverables.
- Fully validating clinical safety is not feasible or justified with synthetic data.
- Supporting every API and local model is engineering breadth without research value.

### Missing contribution if not addressed

- A defensible rubric and rationale for why its labels capture the construct.
- A matched control design and a protocol freeze after pilot.
- A reliability argument for human annotation and a failure analysis for automation.
- An auditable, reusable software artefact rather than a one-off experiment notebook.

### Evidence required for a high grade

- A thematic, critical review that establishes a precise gap and method choice.
- Pilot evidence that the scenarios and rubric are usable.
- Transparent model/configuration records, controls, repeat runs and appropriate analysis.
- A clear technical design, tests, reproducibility evidence and thoughtful limitation discussion.
- A disciplined scope: finished, evaluated core work is more convincing than untested extras.

The course requires originality, clear outcomes, risk planning, justification and evaluation. **Taken from the Research Methods material** — `1.3 Research.pdf`, pp. 5–6 and 19; `6.1Proposals.pdf`, pp. 3–4 and 18–27; `3.1 WritingReports.pdf`, pp. 42–50. The project-specific critique is **your additional recommendation.**

## Stop conditions

Pause the study and consult the supervisor if:

- the pilot produces unexpectedly severe or detailed harmful content;
- an intended annotator reports distress or the protocol requires clinically informed judgement beyond the team’s competence;
- provider terms prohibit the planned storage/evaluation;
- the rubric cannot distinguish emotional validation from endorsement at usable reliability;
- dataset review concludes that release would create a misuse risk.

**Your additional recommendation.**

