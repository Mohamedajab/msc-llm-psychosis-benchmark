# Friday Demonstration Script

## Before the meeting

Do this locally before screen sharing:

```powershell
cd "C:\Users\Moham\OneDrive\Documents\project"
& .\.venv\Scripts\python.exe -c "import numpy, pandas, plotly, streamlit; print('environment OK')"
& .\.venv\Scripts\python.exe scripts\generate_manifest.py --validate
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe scripts\run_pilot.py --plan-output outputs\technical_pilot_plan.json
& .\.venv\Scripts\python.exe -m streamlit run app.py
```

Keep `STATUS.md` open for the exact final test result. Use fixture data for the scheduled demonstration even if OpenRouter is available; it is faster, repeatable and avoids spending quota in front of the supervisor.

## Five-minute primary demonstration

### 0:00-0:40 — Study Overview

Show **Study Overview**.

Say:

> “This is a controlled synthetic benchmark, not a clinical or public-facing chatbot. The planned main design crosses three presentations, three themes, three exact models, two context conditions and two repetitions. That produces 108 six-turn conversations and 648 planned responses. Today I am showing deterministic fixtures and the technical pipeline, not dissertation results.”

Point to the evidence-status distinction:

- **DEMO FIXTURE - NOT RESEARCH DATA**;
- **TECHNICAL PILOT - DESCRIPTIVE ONLY**;
- **MAIN STUDY** planned but not executed.

### 0:40-1:35 — Experiment Runner

Open **Experiment Runner**. Select deterministic fixture mode and one six-turn script. Preview or run both context conditions if the interface makes that quick.

Say:

> “The manipulated context factor is only a frozen prefix. Both conditions still retain the full live conversation. There is no evaluation-revealing system prompt and no instruction to respond safely.”

Show the exact payload preview. For `no_preloaded_context`, turn 1 should contain one user message. For `standardised_preloaded_context`, it should contain the balanced prefix followed by that same user turn.

If running the fixture, point out the prominent fixture label before clicking. Never call it a model result.

### 1:35-2:15 — Transcript & Provenance

Open **Transcript & Provenance** and select the completed fixture run. Inspect turn 6.

Say:

> “This is the key correction to the earlier prototype. Turn 6 contains all five exact earlier user and assistant exchanges followed by the sixth user message. The stored event also contains generation parameters, timestamps, model metadata, status, latency and a hash of the exact request.”

Point out:

- no `system` role;
- previous assistant text appears verbatim;
- the prefix appears only in the selected standardised condition;
- a technical error would be a separate missing/error observation, not scored as safe text;
- raw success files are not overwritten, and resume starts at the first missing turn.

### 2:15-3:10 — Blinded Annotation

Open **Blinded Annotation**.

Say:

> “The annotator sees an opaque item ID and only the conversation through the response being scored. Model, provider, context condition and repetition are hidden. The internal re-identification map is stored separately.”

Show A1, A2 and A3 first, then the exploratory axes. Enter one example rating only if it is clearly a fixture annotation.

Say:

> “Every axis is 0 to 2. I do not sum all seven because some are risk-directed, some protective, and they have different roles. These anchors are conservative working drafts because the authoritative detailed source file was missing; supervisor/research-group confirmation is required before main annotation.”

Mention partial saves, revisions, the adjudication flag and re-rating under a new blinded ID. If reliability is empty, explain that the software correctly returns unavailable until paired ratings exist.

### 3:10-3:40 — NLP Explorer

Open **NLP Explorer**.

Say:

> “This layer does not call another language model. It calculates transparent lexical counts and densities, response/user and turn-to-turn TF-IDF similarity, drift, top terms and—when enough text exists—a small SVD map. These are exploratory language signals, not clinical labels or replacement annotations.”

Show the readable lexicon version/limitations if available.

### 3:40-4:20 — Trajectory Analysis

Open **Trajectory Analysis**.

Say:

> “The analysis unit is the conversation. It summarises A1, A2 and A3 separately, including onset of A1=2, safety intervention, persistence, recovery, final-turn behaviour and missingness. Comparisons are matched by script and repetition, and bootstrap utilities resample whole conversations or script clusters rather than pretending 648 turns are independent.”

Keep fixture/pilot plots visibly labelled and descriptive.

### 4:20-5:00 — Reproducibility & QA

Open **Reproducibility & QA**.

Say:

> “The full manifest is generated and validated without executing it. Dry run makes zero network calls. Live execution has four gates and is bounded to six conversations, 36 successful response slots and 48 HTTP attempts maximum. The meeting can be completed offline.”

Show the current manifest/test status from the page or `STATUS.md`. Finish with the three decisions needed most urgently:

1. approve/revise scripts and working research questions;
2. confirm the authoritative rubric anchors and annotation plan;
3. authorise or defer the bounded technical pilot and freeze exact model endpoints.

## Two-minute emergency offline demonstration

Use this if Wi-Fi, OpenRouter or the browser is unreliable.

### 0:00-0:25

Open **Study Overview** and say:

> “This is an offline deterministic demonstration. Fixture outputs are not research data. The 108-row manifest represents the planned design; it has not been executed.”

Show the `108 conversations / 648 response slots` summary.

### 0:25-0:55

Open **Experiment Runner**, select fixture/dry-run mode, and show turn 1 versus turn 6 request previews.

Say:

> “The outgoing payload proves full history accumulation and no system cue; dry-run cannot contact a provider.”

### 0:55-1:20

Open **Transcript & Provenance** for a saved fixture record.

Show exact messages, payload hash, model/status fields and the fixture label.

### 1:20-1:45

Open **Blinded Annotation**.

Show hidden experimental identity and the seven separate 0-2 axes. State the draft-anchor caveat and no-total rule.

### 1:45-2:00

Open **NLP Explorer** or **Trajectory Analysis**.

Say:

> “The added computational analysis is offline and explainable, and all inferential units remain whole conversations. The next step is supervisor approval and a bounded technical pilot—not the full study.”

## Terminal-only fallback

If Streamlit itself cannot be shown, use PowerShell:

```powershell
cd "C:\Users\Moham\OneDrive\Documents\project"
& .\.venv\Scripts\python.exe scripts\generate_manifest.py --validate
& .\.venv\Scripts\python.exe scripts\run_pilot.py --plan-output outputs\technical_pilot_plan.json
& .\.venv\Scripts\python.exe -m pytest tests\test_payload_history.py tests\test_runner_storage.py tests\test_annotation.py tests\test_nlp.py tests\test_trajectory_analysis.py -q
```

Then open these files in VS Code:

- `outputs/experiment_manifest.csv`;
- one generated dry-run payload file reported by `run_pilot.py`;
- `config/rubric.yaml`;
- `config/nlp_lexicons.yaml`;
- `docs/ARCHITECTURE.md`.

## Questions to answer carefully

**“Are these results?”**  
No. Fixture outputs are workflow data. Any six-conversation live run is a technical pilot and descriptive only. The main study is the unexecuted 108-conversation manifest.

**“Is this measuring psychosis?”**  
No. It measures prespecified textual response behaviours in synthetic prompts. Presentation conditions are not diagnoses and there are no patient participants.

**“Why no single score?”**  
The axes differ in direction and role. A1/A2 are risk-directed primary outcomes and A3 is protective. Combining all seven would conceal those distinctions and imply unsupported scale validity.

**“Why not use another LLM as judge?”**  
Human annotation is the reference workflow. The non-LLM NLP layer is transparent. Any automated baseline is secondary, grouped by conversation and guarded against insufficient data. Automated judging is not required for the Friday demonstration.

**“Can it reproduce remote outputs?”**  
It can reproduce configuration, execution order, exact payloads, hashes and local derived analysis. A remote provider may not reproduce identical text even with a recorded seed, so the raw response is preserved and the limitation is reported.
