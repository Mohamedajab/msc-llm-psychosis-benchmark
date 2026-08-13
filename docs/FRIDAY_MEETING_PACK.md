# Friday Supervisor Meeting Pack

**Student:** Mohamed Ajab  
**Programme:** MSc Advanced Computer Science, Loughborough University  
**Working title:** A Controlled Multi-Turn Benchmark for Psychosis-Related Belief Reinforcement in Large Language Model Chatbots  
**Meeting build date:** 14 August 2026  
**Scope:** local research prototype and protocol review, not a presentation of dissertation results

## One-minute summary

The prototype now represents the proposed study as a controlled, inspectable software pipeline rather than “one chatbot talks and another chatbot judges it.” Nine synthetic six-turn scripts generate a balanced 72-conversation plan. A common runner sends the exact full dialogue history, varies only a frozen prefix for the context manipulation, and stores every provider-bound payload and response/error with provenance. Human ratings are blinded and use seven separate draft 0-2 axes. A transparent offline NLP layer and conversation-level trajectory analysis provide computational evidence without relying on an LLM judge.

The Friday build is demonstrable entirely with deterministic fixtures. Those outputs are clearly **DEMO FIXTURE - NOT RESEARCH DATA**. An optional live technical pilot is bounded at four conversations/24 calls and double-gated. It has not been treated as main-study evidence. The full 72-conversation study has not been run.

## Three evidence categories

| Category | What exists | What may be claimed |
|---|---|---|
| **DEMO FIXTURE - NOT RESEARCH DATA** | Deterministic safe/risk-prone response profiles for offline workflow testing | The pipeline works on controlled fixture inputs; nothing about real-model safety |
| **TECHNICAL PILOT - DESCRIPTIVE ONLY** | A fixed, explicitly gated plan for 1 script x 2 models x 2 contexts x 6 turns | Transport/storage/feasibility observations only, if actually executed |
| **MAIN STUDY** | Validated 72-row manifest and analysis protocol | The design is ready for review; no empirical model comparison until authorised execution and annotation |

## Main-study design

```text
3 presentation levels
x 3 themes
x 2 exact model slots
x 2 context conditions
x 2 repetitions
= 72 conversations

72 conversations x 6 turns = 432 planned assistant responses
```

Presentation levels are `control`, `ambiguous` and `fixed_belief`. Themes are perceived monitoring, personally directed messages and an unsupported special AI relationship/hidden access. Context is either `no_preloaded_context` or `standardised_preloaded_context`. These are synthetic stimulus conditions, not diagnoses.

## What the prototype can show live

### Experimental control

- exactly nine versioned scripts with six turns each;
- a balanced deterministic 72-row manifest;
- exact model slots and fixed generation configuration;
- frozen theme-specific prefixes shared across presentation levels;
- no model/presentation/rubric metadata in target-facing messages.

### Genuine multi-turn execution

- turn 1 contains the current user message, plus the prefix only in the standardised condition;
- turn 6 contains all five earlier user/assistant exchanges and current user turn 6;
- no system message tells the model it is evaluated or asks it to behave safely;
- deterministic provider captures the exact payload for verification;
- dry run constructs all six requests with zero network calls;
- resume begins at the first missing successful turn.

### Provenance

- immutable run header;
- one exclusive file per successful turn and sequenced files for errors;
- exact messages, request parameters, timestamps and payload SHA-256;
- requested/resolved model and provider metadata where available;
- finish reason, usage, IDs, latency, retry count and typed errors;
- no API key in stored records.

### Human measurement

- seven individual ordinal 0-2 axes;
- A1, A2 and A3 retained as separate primary outcomes;
- no inappropriate seven-axis total;
- opaque blinded IDs and a separate internal re-identification map;
- response displayed with conversation only up to that point;
- partial-save/resume, revisions, notes and adjudication flag;
- deterministic re-rating under new IDs;
- per-axis exact agreement and linear-weighted kappa with correct intra-/inter-rater labels.

### Computational analysis

- transparent versioned marker counts/densities and basic language statistics;
- offline TF-IDF response/user and turn-to-turn similarity/drift;
- grouped top terms and a guarded SVD map;
- conversation-level onset, persistence, recovery, final-turn and missingness measures;
- matched model/context descriptions;
- bootstrap resampling of whole conversations or script clusters, never individual turns;
- a secondary grouped TF-IDF/logistic-regression baseline that refuses insufficient data.

## Important honest caveat about the rubric

The requested separate detailed rubric source file was not available during the repository audit. Axis identities/directions are supplied, but `config/rubric.yaml` uses conservative reconstructed working definitions and anchors. The file is visibly marked **draft research rubric; not clinically validated**. It must be reviewed and frozen with the supervisor/research group before main annotation. Changing it later requires a new rubric version; old and new labels must not be silently pooled.

## Five-minute agenda

Use [DEMO_SCRIPT.md](DEMO_SCRIPT.md) for exact narration.

| Time | Screen | Point to establish |
|---:|---|---|
| 0:00-0:40 | Study Overview | planned design, 72/432, and evidence-status separation |
| 0:40-1:35 | Experiment Runner | one offline fixture run and/or exact six-payload preview |
| 1:35-2:15 | Transcript & Provenance | turn-6 full history, no system cue, hashes and metadata |
| 2:15-3:10 | Blinded Annotation | hidden factors, seven separate axes, draft-anchor caveat |
| 3:10-4:10 | NLP Explorer / Trajectory Analysis | non-LLM features and conversation-level analysis |
| 4:10-5:00 | Reproducibility & QA | tests/manifest status and decisions requested |

## Commands for the meeting laptop

From PowerShell:

```powershell
cd "C:\Users\Moham\OneDrive\Documents\project"
& .\.venv\Scripts\python.exe -m streamlit run app.py
```

Offline pilot plan/dry-run:

```powershell
& .\.venv\Scripts\python.exe scripts\run_pilot.py
```

Manifest validation:

```powershell
& .\.venv\Scripts\python.exe scripts\generate_manifest.py --validate
```

Do not attempt a live call during the meeting unless it was intentionally approved, the exact slugs were rechecked, quota is understood and the offline demonstration has already succeeded.

## If the internet/OpenRouter fails

Nothing essential is lost. The deterministic provider, dry-run payloads, manifest, annotation, NLP and analysis all run locally. Follow the two-minute emergency path in [DEMO_SCRIPT.md](DEMO_SCRIPT.md). State clearly that this is a fixture demonstration and show the payload/provenance invariants rather than waiting on a provider.

## Validation evidence to have open

Use `STATUS.md` for the final recorded results after integration. The meeting-ready checks are:

```powershell
& .\.venv\Scripts\python.exe scripts\generate_manifest.py --validate
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m ruff check app.py src scripts tests
& .\.venv\Scripts\python.exe -m ruff format --check app.py src scripts tests
& .\.venv\Scripts\python.exe -m compileall -q app.py src scripts tests
```

The final integrated suite is recorded in `STATUS.md`: 73 tests passed, Ruff and compilation passed, and the seven-view Streamlit interaction suite completed without a network call.

## Decisions requested from the supervisor

The priority decisions are:

1. approve or revise the working title, aim and four research questions;
2. approve the three presentation definitions and nine scripts as parallel, ethical stimuli;
3. recover/confirm the authoritative detailed seven-axis anchors and freeze rubric version 1;
4. approve primary outcomes (A1, A2, A3 separately), A3 threshold and trajectory definitions;
5. confirm annotator count, training, re-rating fraction and adjudication procedure;
6. confirm whether the four-conversation technical pilot may be run and whether it needs an ethics/provider-terms check first;
7. approve the rule for selecting/fixing exact model endpoints before main execution;
8. confirm that the grouped supervised baseline remains secondary and that no automated judge is required for the core dissertation.

The expanded decision sheet is [DECISIONS_FOR_SUPERVISOR.md](DECISIONS_FOR_SUPERVISOR.md).

## What is not being claimed

- No real-model comparative result is claimed in this pack.
- No live OpenRouter call is claimed unless a raw record exists and `STATUS.md` records it.
- The technical pilot is not a sample from which to infer model safety.
- Fixture responses are not empirical observations.
- The rubric has not been clinically or psychometrically validated.
- Lexical features are not clinical labels or substitutes for human judgement.
- The baseline is not a validated automated scorer.
- Synthetic transcripts do not establish clinical harm, causation or population prevalence.
- This is not a production service, public-facing chatbot or NHS system.

## Immediate next actions after the meeting

1. Record the supervisor's decisions and update/freeze protocol versions before generating any new evidence.
2. If authorised, execute only the bounded technical pilot, inspect all 24-or-fewer raw observations and repair any provenance/resume issue before considering expansion.
3. Conduct rubric training and a small blinded annotation/re-rating exercise; report per-axis agreement before main annotation.

See [NEXT_AFTER_EXAMS.md](NEXT_AFTER_EXAMS.md) for the longer restart sequence and [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) for the claim boundary.
