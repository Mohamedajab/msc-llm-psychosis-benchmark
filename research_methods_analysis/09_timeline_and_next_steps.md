# Timeline, Minimum Viable Project and Immediate Actions

## Planning principle

Use activities, milestones, dependencies and a regularly updated plan. The course recommends a PID/brief containing aim, objectives, deliverables, risks, schedule and milestones, and a project plan using activities, estimates and Gantt tracking. **Taken from the Research Methods material** — `week 89  ProjectMgmt.pptx`, slides 7–28 and 53–56.

The following is a 16-week working plan. Move dates to match the actual dissertation calendar after checking the programme handbook and supervisor expectations. **Your additional recommendation.**

| Week | Primary output | Key work | Milestone / decision |
|---|---|---|---|
| 1 | Scope memo | Confirm non-clinical boundary, draft title/aim/RQs, ask ethics question. | Supervisor agrees direction or requests change. |
| 2 | Search protocol | Build search concepts, database queries, inclusion criteria and evidence matrix. | Search log started. |
| 3 | Literature map | Screen foundational work, identify gap, create research territory map. | Gap/method rationale drafted. |
| 4 | Proposal v1 | Finalise RQs, objectives, risk register, model selection rule and budget. | Proposal review. |
| 5 | Benchmark v0 | Draft safe categories, controls, schema and codebook. | Safeguarding/ethics check before pilot. |
| 6 | Pipeline foundation | Implement schemas, mocked adapter, storage, unit tests and manifest. | Local end-to-end fixture passes. |
| 7 | Pilot protocol | Add one permitted API adapter; create pilot annotation export. | Pilot readiness review. |
| 8 | Pilot results | Run 8 scenarios × 2 models × 2 runs; code pilot subset. | Revise once and lock dataset/rubric/protocol. |
| 9 | Main collection A | Execute half of the main runs, monitor cost/errors/completeness. | Data-quality checkpoint. |
| 10 | Main collection B | Complete 288 trajectories and build blinded annotation set. | Collection manifest frozen. |
| 11 | Annotation | Double-code 96 stratified trajectories; record disagreements. | Reliability report. |
| 12 | Analysis | Import labels, calculate descriptive statistics, confidence intervals and models/permutation tests. | Results tables frozen. |
| 13 | Figures and evaluation | Create required graphs, analyse failure cases, validity and ethics limitations. | Results narrative drafted. |
| 14 | Write chapters | Complete methods, implementation, results and evaluation; update literature review. | Full draft to supervisor. |
| 15 | Revision and verification | Address feedback, rerun analysis from clean snapshot, proof figures/references. | Reproducibility check passes. |
| 16 | Final edit | Abstract, conclusion, appendices, consistency, AI-use declaration and final proofread. | Submission-ready package. |

## Minimum viable project

Deliver the MVP if time or access becomes constrained:

- 12 safe scenarios: eight target and four neutral controls.
- Three model endpoints, two runs each and six turns: 72 trajectories.
- A tested Python runner with raw metadata records.
- A pilot-tested rubric and independent coding of a balanced subset.
- Descriptive comparison, reliability results, limitations and reproducibility package.

**Your additional recommendation.** The course advises realistic scope, clear outcomes and available resources. `6.1Proposals.pdf`, pp. 3–4 and 20–21.

## Optional extensions, only after the core passes

- One local/open-weight adapter.
- Prompt-paraphrase robustness analysis.
- Lightweight, blinded annotation interface.
- Automated judge calibrated on a held-out human-labelled subset.
- Docker/container reproducibility and a public redacted demo.

**Your additional recommendation.**

## Ten immediate next actions

1. Send [10_questions_for_supervisor.md](10_questions_for_supervisor.md) to the supervisor and obtain a decision on scope and ethics route.
2. Confirm the dissertation word limit, marking criteria, format and AI-use policy from the current programme documentation.
3. Convert the recommended title, aim, RQs and objectives into a one-page proposal.
4. Start the documented literature search in ACM, IEEE, Scopus/Web of Science, PubMed and PsycINFO where available.
5. Create the evidence matrix and search log before reading further papers.
6. Draft the 24-scenario schema and six safe conversation stages without writing detailed sensitive content.
7. Draft the annotation codebook, especially the belief-reinforcement versus emotion-validation distinction.
8. Create the Python repository, schema validator, mocked model adapter and test fixture.
9. Obtain model-provider pricing, versioning, storage and research-use information; set a budget ceiling.
10. Create a live risk register and a Gantt/WBS with the 16 milestones above.

Actions 1–10 are **your additional recommendation**, structured using the course guidance on project definition, SMART objectives, risks, milestones and Gantt planning. `week 89  ProjectMgmt.pptx`, slides 6–28.

