# Controlled Multi-Turn LLM Psychosis-Related Response Benchmark

MSc Advanced Computer Science dissertation research artefact.

This repository implements a controlled, reproducible benchmark for evaluating how large language model chatbots respond to psychosis-related unsupported interpretations across six-turn conversations.

The benchmark is a **synthetic research evaluation**. It is not a clinical, diagnostic, or therapeutic system.

## Final study status

**Study version:** `study-v2.1.0`
**Status:** COMPLETE
**Main-study conversations:** 72 / 72
**Assistant responses:** 432 / 432
**Human annotations:** 432 / 432
**Supplementary LLM-judge annotations:** 1,296 / 1,296
**Final response truncations:** 0

The completed quantitative analysis is frozen. Main-study collection and LLM-judge collection must not be rerun.

## What is included

The repository contains the application, experiment configuration, nine frozen scenario scripts,
three standardised context histories, the 72-row study manifest, protocol bundles, tests and a
small demonstration dataset.

The completed raw conversations, human annotations, judge records and private analysis outputs
are preserved locally but excluded from Git. They contain full dialogue and detailed research
provenance. A clean clone can run the application with the demonstration fixtures and inspect the
complete method, but reproducing the reported numerical results also requires the separately
controlled research evidence.

The study inputs are synthetic and were written as controlled six-turn scripts. No patient or
participant dataset was used. Files under `config/personas/` are retired prototype metadata and
are not loaded by the final experiment.

## Experimental design

The final study uses a balanced factorial design:

- 3 presentation levels:
  - `control`
  - `ambiguous`
  - `fixed_belief`
- 3 scenario themes:
  - `monitoring`
  - `personal_messages`
  - `ai_relationship`
- 2 target models:
  - `minimax/minimax-m3:free`
  - `nvidia/nemotron-3-super-120b-a12b:free`
- 2 context conditions:
  - `no_preloaded_context`
  - `standardised_preloaded_context`
- 2 repetitions
- 6 turns per conversation

Total:

`3 × 3 × 2 × 2 × 2 = 72 conversations`

`72 × 6 = 432 assistant responses`

## Research questions

**RQ1** — How does presentation level affect belief-confirming and harm-enabling responses across a six-turn exchange?

**RQ2** — How do MiniMax M3 and NVIDIA Nemotron 3 Super differ on the primary A1, A2 and A3 outcomes under the qualified generation-v4 configuration?

**RQ3** — Does standardised preloaded context change response trajectories compared with no preloaded context?

**RQ4** — At what turn do high-risk confirmation or protective safety intervention first appear, persist or recover?

## Human annotation

Human annotation is the primary source of behavioural evidence.

The frozen rubric contains seven axes.

### Primary axes

- **A1 — Belief Confirmation**
- **A2 — Harm Enablement**
- **A3 — Safety Intervention**

### Exploratory axes

- **B1 — Epistemic Grounding Failure**
- **B2 — Reality / AI Boundary Blurring**
- **B3 — Self-Regulation / Dependence Undermining**
- **C1 — Appropriate Challenge Quality**

Higher A1, A2, B1, B2 and B3 scores represent less desirable behaviour.

Higher A3 and C1 scores represent more desirable behaviour.

The frozen rubric is stored in:

`config/rubric.yaml`

The annotation procedure is documented in:

`docs/ANNOTATION_GUIDE.md`

All 432 final responses received a human annotation.

The final study used one human annotator. No claim of independent human inter-rater reliability is made.

## Supplementary LLM judges

Three separately run blinded LLM judges were used for supplementary validation:

- DeepSeek V4 Pro
- DeepSeek V4 Flash
- GLM-5.3-Flash

The judges received the frozen rubric and blinded response material.

They were not given:

- target-model identity;
- experimental condition;
- human ratings;
- other judge ratings.

Each judge rated the full set of 432 responses.

Total supplementary judge ratings:

`432 × 3 = 1,296`

Human ratings remain the primary behavioural evidence.

Judge methodology is documented in:

`docs/LLM_JUDGES.md`

## Analysis

The final dissertation analysis pipeline is divided into three reproducible stages.
These are the supported scripts for the reported dissertation outputs.
`scripts/analyse_study.py` is retained as an earlier analysis scaffold and is
not used to regenerate the final V1-V3 results.

### V1 — Descriptive and agreement analysis

Script:

`scripts/analyse_completed_study.py`

Produces:

- human response-level summaries;
- model summaries;
- presentation-level summaries;
- context summaries;
- theme summaries;
- turn-level summaries;
- conversation trajectory summaries;
- individual human–judge agreement;
- confusion counts;
- three-judge consensus comparison.

### V2 — Primary research-question analysis

Script:

`scripts/analyse_research_questions.py`

Produces:

- matched RQ1 presentation-level comparisons;
- matched RQ2 model comparisons;
- matched RQ3 context comparisons;
- RQ4 onset, persistence and recovery summaries;
- primary dissertation figures.

Inferential comparisons use conversation-level matched outcomes rather than treating the six repeated turns as independent observations.

The primary inferential procedure uses:

- Wilcoxon signed-rank tests;
- rank-biserial effect sizes;
- seeded 95% percentile bootstrap confidence intervals;
- Holm multiple-comparison correction within each research-question family.

Valid structural N/A values for A2 and A3 are excluded from numeric analyses and are never converted to zero.

### V3 — Exploratory analysis

Script:

`scripts/analyse_final_exploratory.py`

Produces:

- exploratory rubric-axis comparisons;
- theme comparisons;
- model × presentation analyses;
- presentation × time analyses;
- early-versus-late trajectory summaries;
- human versus three-judge majority agreement.

Exploratory findings are secondary to the primary A1/A2/A3 research-question analyses.

## Main findings

The completed analysis found that:

- presentation level showed clearer differences on the primary behavioural outcomes than target-model identity within this benchmark;
- ambiguous presentations were particularly challenging;
- ambiguous presentations produced higher belief confirmation and harm enablement than control on supported primary comparisons;
- fixed-belief presentations showed lower harm enablement and higher safety intervention than ambiguous presentations on supported primary comparisons;
- the presentation effect was not monotonic;
- no statistically supported overall MiniMax-versus-Nemotron difference was detected on the primary A1/A2/A3 outcomes;
- no statistically supported overall effect of the standardised preloaded context was detected on the primary A1/A2/A3 outcomes;
- multi-turn analysis revealed onset, persistence and recovery patterns that were not visible from overall response averages;
- monitoring scenarios were particularly challenging on several descriptive and exploratory outcomes;
- presentation × time analysis showed a supported difference in A1 trajectory between ambiguous and fixed-belief presentations;
- LLM-judge agreement with the human annotator varied substantially by rubric axis;
- agreement was stronger on some axes, including A1 and C1, and weaker on A2, A3 and some exploratory axes;
- the variation in judge agreement supports retaining human annotation as the primary evidence source.

These results describe the tested benchmark configuration only.

They should not be interpreted as:

- clinical-safety guarantees;
- evidence that one model family is universally safer;
- clinical diagnosis;
- evidence of causal effects on psychosis;
- evidence of real-world clinical outcomes.

## Repository structure

```text
app.py
    Streamlit research interface.

config/
    Frozen models, scenarios, histories, rubric, judge configuration,
    governance settings and runtime technical amendments.

src/
    Core Python implementation for collection, configuration,
    persistence, annotation, judging, provider handling,
    evidence validation and trajectory analysis.

scripts/
    Reproducible command-line utilities, study tooling
    and final V1–V3 analysis scripts.

tests/
    Automated validation of experiment configuration,
    storage, annotation, provider handling, collection,
    study execution, judging and analysis behaviour.

protocol/
    Frozen protocol bundles, including the final
    study-v2.1.0 bundle.

docs/
    Architecture, protocol, annotation, data-management,
    provider and technical-incident documentation.

outputs/
    Experiment manifest, data dictionary and generated
    project artefacts.

data/
    Public demonstration fixtures and local research-evidence
    locations. Private completed evidence is ignored by Git.
```

## Research application

The Streamlit interface is organised around:

1. Overview
2. Collection
3. Annotation
4. LLM Judges
5. Analysis
6. Evidence & QA

The interface supports inspection of the research workflow while keeping live model operations behind explicit technical controls.

Run the application locally with:

```text
streamlit run app.py
```

## Important evidence boundaries

Demonstration fixtures, technical pilots, calibration runs and the final main study occupy separate evidence namespaces.

Technical engineering evidence is not treated as dissertation behavioural evidence.

Historical Pilot V4 and Pilot V5 results are preserved as immutable failed technical evidence.

Pilot V6 qualified the final MiniMax/Nemotron pair under the generation-v4 configuration.

The final main-study evidence is stored separately from pilot and demonstration namespaces.

The main study is complete and must not be resumed or regenerated.

Technical collection interruptions are documented in:

`docs/MAIN_STUDY_TECHNICAL_INCIDENTS.md`

## Main-study technical reliability

The final study contains:

- 72 completed conversations;
- 432 completed response slots;
- 145 recorded technical API error events;
- 127 automatic recoveries;
- 0 final truncations;
- one approved finish-metadata anomaly.

Technical errors are retained as provenance.

Failed API attempts are not behavioural responses.

Previously accepted successful responses are immutable and are not regenerated during recovery.

## Protocol and frozen configuration

The final study protocol is:

`protocol/study-v2.1.0/`

The final configuration preserves:

- exact target-model identifiers;
- frozen scenario scripts;
- frozen standardised context prefixes;
- repetition seeds;
- generation configuration;
- frozen annotation rubric;
- study governance;
- technical provenance.

Historical protocol material is retained separately to preserve the development record.

## Data and privacy

Credentials and private research evidence are excluded from Git where required.

Do not commit:

- `.env`;
- API keys;
- credentials;
- private re-identification maps;
- private analysis outputs not intended for repository publication;
- temporary local working files.

See:

`docs/DATA_MANAGEMENT.md`

## Local setup

Activate the existing virtual environment:

```text
.\.venv\Scripts\Activate.ps1
```

For a clean Python 3.12 environment, create the virtual environment and install the tested
dependency set:

```text
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-lock.txt
```

`requirements.txt` provides the supported dependency ranges; `requirements-lock.txt` records the
exact environment used for final validation.

## Offline validation

Normal repository validation is designed to run without making target-model API requests.

Run:

```text
python -m pytest -q
python -m ruff check app.py src scripts tests --exclude scripts/analyse_completed_study.py,scripts/analyse_research_questions.py,scripts/analyse_final_exploratory.py
python scripts\check_documentation_links.py
python scripts\protocol_bundle.py --verify
```

The three final analysis scripts are excluded from formatting checks because their verified file
hashes form part of the frozen result record. Their behaviour is covered by the test and release
verification suites.

Do not rerun:

- the completed main study;
- the completed LLM judges;
- historical immutable pilot evidence.

## Verify the completed study

Run the final offline verification from the repository root:

```text
python scripts/verify_final_release.py
```

The command checks the 72 completed conversations, 432 responses, primary human annotations,
three supplementary judge sets, protocol-bundle integrity, frozen analysis hashes, reported-result
values and repository safety. It does not make API requests or modify research evidence.

## Final analysis scripts

The dissertation findings were produced using:

```text
scripts/analyse_completed_study.py
scripts/analyse_research_questions.py
scripts/analyse_final_exploratory.py
```

The completed V1, V2 and V3 analysis outputs were frozen after final verification.

Analysis must not be altered merely to obtain different statistical results.

## Reproducibility

The complete local research record retains:

- the final experiment manifest;
- the frozen rubric;
- scenario definitions;
- context prefixes;
- exact target-model configuration;
- protocol bundles;
- human annotation evidence;
- supplementary judge evidence;
- technical incident provenance;
- analysis scripts;
- automated tests;
- data dictionary;
- analysis freeze information.

The tracked repository preserves the software, planned-study material and verification logic.
Private evidence remains outside Git in accordance with the documented data-management boundary.

## Key documentation

Final project documentation includes:

- `docs/RESEARCH_PROTOCOL.md`
- `docs/ARCHITECTURE.md`
- `docs/ANNOTATION_GUIDE.md`
- `docs/DATA_MANAGEMENT.md`
- `docs/EXECUTION_POLICY.md`
- `docs/PROVIDER_POLICY.md`
- `docs/LLM_JUDGES.md`
- `docs/MAIN_STUDY_RUNBOOK.md`
- `docs/MAIN_STUDY_TECHNICAL_INCIDENTS.md`
- `docs/FINAL_STUDY_PROVENANCE.md`

Some protocol documents intentionally preserve the pre-collection state used to freeze Study
V2.1. They are historical provenance; the status at the top of this README describes the
completed project.

## Dissertation scope

The project evaluates observable language-model response behaviour under controlled synthetic inputs.

It does not evaluate real patients and does not claim to diagnose psychosis.

The benchmark focuses on measurable conversational behaviours such as:

- belief confirmation;
- harm-enabling content;
- safety intervention;
- epistemic grounding failure;
- reality / AI boundary blurring;
- dependence-undermining behaviour;
- challenge quality;
- multi-turn onset;
- persistence;
- recovery.

The core contribution is the combination of controlled factorial comparison, full multi-turn conversation trajectories, blinded human annotation, supplementary blinded LLM judges and reproducible evidence handling.

---

**Author:** Mohamed Ajab
**Programme:** MSc Advanced Computer Science
**Institution:** Loughborough University
**Academic year:** 2025–2026
