# MSc LLM psychosis benchmark

An auditable, configuration-driven benchmark of how two exact language-model endpoints
respond across six-turn conversations containing controlled unsupported interpretations.
Main-study collection is in progress. Partial responses are immutable research evidence but are
not results and must not be analysed as a completed study.

## Prospective Study V2 design

The final `study-v2.1.0` protocol will cross three presentation levels, three themes, two models, two
context conditions and two repetitions: 72 conversations and 432 planned responses.

- fixed Model A: `minimax/minimax-m3:free`
- fixed Model B: `nvidia/nemotron-3-super-120b-a12b:free`, qualified jointly with MiniMax
  by Pilot V6 under generation-v4

The reduction from the historical 108-conversation plan was adopted before data collection
and is documented in `docs/PROTOCOL_DEVIATION_STUDY_V2.md`. Prospective generation-v4 adds no
target-facing concision/length instruction, uses model-native reasoning with reasoning traces
excluded, a non-binding 4096-token emergency envelope, and the unchanged repetition seeds
20260814/20260815.

## Evidence boundaries

Demo fixtures, Pilot V1, Pilot V2, Pilot V3, the Nemotron endpoint screen, failed Pilot V4,
failed Pilot V5, the benign generation calibration, replacement-screen v2, Pilot V6 and the
main study are distinct namespaces. Technical evidence is not dissertation data. Pilot V1-V5,
the endpoint screen and calibration records are immutable. Raw responses, assessments,
annotations, private maps and credentials are ignored by Git.

## Offline validation

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m ruff check app.py src scripts tests
& .\.venv\Scripts\python.exe -m ruff format --check app.py src scripts tests
& .\.venv\Scripts\python.exe scripts\generate_manifest.py --validate
& .\.venv\Scripts\python.exe scripts\audit_pilot_v4.py
& .\.venv\Scripts\python.exe scripts\audit_pilot_v5.py
& .\.venv\Scripts\python.exe scripts\audit_generation_budget.py
& .\.venv\Scripts\python.exe scripts\run_generation_calibration.py # offline only
& .\.venv\Scripts\python.exe scripts\run_pilot_v5.py
& .\.venv\Scripts\python.exe scripts\assess_pilot_v5.py # recomputes FAIL from immutable V5 evidence
& .\.venv\Scripts\python.exe scripts\run_study.py
& .\.venv\Scripts\python.exe scripts\protocol_bundle.py --verify
```

Offline runner invocations make zero network calls. Model identities come exclusively from
versioned configuration; `.env` cannot override them. Live commands require deliberate
independent gates and current exact catalogue qualification.

Pilot V4 completed 24/24 slots but failed its frozen qualification because 12 responses were
truncated at generation-v2's 512-token limit. It cannot be rerun, resumed into PASS or
rewritten. Pilot V5 ran under generation-v3 (1024 tokens) and completed 24/24 slots, but 11
responses were truncated, so it is now closed as immutable failed technical evidence and cannot
be resumed into PASS.

The content-free V4/V5 audit found no stored reasoning-token telemetry. A separate six-request
benign calibration then showed native-reasoning truncation at 1024 twice and at 2048 once,
reasoning-off `stop` at 1024 twice, and native-reasoning `stop` at 4096. Reported reasoning usage
supports a material contribution to budget exhaustion under the tested endpoint; it does not
rewrite Pilot V4/V5 or constitute behavioural evidence. See
`docs/GENERATION_V4_CALIBRATION.md`.

Nemotron failed the frozen generation-v2/v3 technical qualification. Pilot V6 subsequently
qualified the original MiniMax/Nemotron pair under generation-v4: 24/24 responses finished
with `stop`, with zero truncation. The historical Pilot V4/V5 verdicts remain unchanged.
The final pair is `QUALIFIED`; the rubric and annotation procedure are frozen, data-management
arrangements are confirmed, and the completed June 2026 Ethics Awareness Form records that no
further ethical review is required. The main study remains `BLOCKED` until the active bundle is
created and verified. No main-study responses exist.

The primary Study V2 path requires an original-pair generation-v4 Pilot V6 PASS and a verified
active study-v2.1.0 bundle before live collection. Only if V6 fails does the preserved governed
replacement-screen workflow activate, followed by a separately versioned future Pilot V7.
A future technical PASS is not academic approval.

The Streamlit workspace is organised around five areas: Overview, Collection, Annotation,
Analysis, and Evidence & QA. Main Study Collection reads progress from append-only raw evidence
and can later launch a guarded background worker after preflight passes. Offline fixture and
request-preview tools remain separate under Evidence & QA. The interface does not bypass the
active-bundle or technical readiness gates.

See `docs/MAIN_STUDY_RUNBOOK.md`, `docs/RESEARCH_PROTOCOL.md` and
`docs/MAIN_STUDY_GO_NO_GO_CHECKLIST.md` before any collection. The frozen human-rating
procedure is in `docs/ANNOTATION_GUIDE.md`, and rubric v1.0.0 is frozen in
`config/rubric.yaml`.

Technical collection interruptions are recorded factually in
`docs/MAIN_STUDY_TECHNICAL_INCIDENTS.md`.
