# Friday Research Prototype Plan

Target: meeting-ready local build for Friday 14 August 2026, 10:00 UK time.

## Milestone 0 - Audit and preserve

- [x] Confirm the repository root and Git state.
- [x] Inspect existing application, configuration, tests, documentation, and archived prototype.
- [x] Locate and read the revised proposal and meeting pack where available.
- [x] Record unavailable requested inputs without inventing their contents.

Acceptance criteria:

- Existing research-method notes and unrelated user files remain intact.
- The active application root is documented in `STATUS.md`.

Validation:

```powershell
git status --short --branch
rg --files -g '!**/.git/**' -g '!**/.venv/**'
```

## Milestone 1 - Freeze experimental configuration

- [x] Add three presentation levels, three themes, and nine parallel six-turn scripts.
- [x] Add balanced frozen context prefixes, two exact model slots, generation configuration, and a versioned seven-axis rubric.
- [x] Generate and validate the balanced 72-run study manifest.
- [x] Add configuration hashes and a data dictionary.

Acceptance criteria:

- Exactly nine scripts, each with six non-graphic turns.
- Exactly 72 unique balanced manifest rows.
- No target-facing message contains condition labels, rubric language, diagnoses, or evaluation instructions.

Validation:

```powershell
& .\.venv\Scripts\python.exe scripts\generate_manifest.py --validate
& .\.venv\Scripts\python.exe -m pytest tests\test_catalogue.py tests\test_manifest.py -q
```

## Milestone 2 - Correct runner, providers, and provenance

- [x] Implement a payload-inspectable deterministic fixture provider and robust OpenRouter provider.
- [x] Accumulate full dialogue history on every request and apply the frozen prefix only in the standardised condition.
- [x] Add dry-run, resume, immutable raw JSON storage, error separation, retries, and complete provenance.
- [x] Add an explicitly gated maximum 24-call technical-pilot command.

Acceptance criteria:

- Payload tests prove exact message order for all six turns.
- Dry runs make zero provider/network calls.
- Resume never duplicates successful turns or overwrites raw evidence.
- API keys never enter records or logs.

Validation:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_payload_history.py tests\test_runner_storage.py tests\test_providers.py -q
& .\.venv\Scripts\python.exe scripts\run_pilot.py --help
```

## Milestone 3 - Blinded seven-axis annotation

- [x] Implement the draft seven-axis 0-2 models and validation.
- [x] Add blinded annotation items, safe progress persistence, incomplete-item return, notes, and adjudication flags.
- [x] Add re-rating sample support and tidy export.
- [x] Add exact agreement and linearly weighted Cohen's kappa utilities.

Acceptance criteria:

- Model, provider, context, and repetition are absent from annotator-facing records.
- No combined seven-axis total is produced.
- Scores outside 0-2 are rejected.

Validation:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_annotation.py tests\test_reliability.py -q
```

## Milestone 4 - Transparent NLP and trajectory analysis

- [x] Add versioned readable lexical patterns and deterministic non-LLM text features.
- [x] Add TF-IDF similarities, drift, grouped term summaries, and offline projections where data permit.
- [x] Add conversation-level rubric trajectory measures and cluster-level bootstrap utilities.
- [x] Add a guarded grouped supervised-baseline scaffold.
- [x] Add the disabled optional judge scaffold (P1; not required for core validity).

Acceptance criteria:

- NLP works offline and handles empty/short text.
- Analysis never treats turns as independent experimental units.
- Baseline refuses insufficient or single-class data and never leaks a conversation across folds.

Validation:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_nlp.py tests\test_trajectory_analysis.py tests\test_baseline.py -q
```

## Milestone 5 - Research dashboard

- [x] Implement Overview, Runner, Provenance Inspector, Blinded Annotation, NLP Explorer, Trajectory Analysis, and Reproducibility/QA views.
- [x] Add exact payload previews, live-execution confirmation, resume controls, downloads, and useful empty states.
- [x] Mark every fixture output and fixture annotation as `DEMO FIXTURE - NOT RESEARCH DATA`.

Acceptance criteria:

- Normal startup performs no network request.
- The app is usable end to end with deterministic fixtures.
- Mock/pilot/main-study status is unambiguous on every relevant view.

Validation:

```powershell
& .\.venv\Scripts\python.exe -m streamlit run app.py
& .\.venv\Scripts\python.exe -c "from streamlit.testing.v1 import AppTest; a=AppTest.from_file('app.py').run(); assert not a.exception"
```

## Milestone 6 - Meeting exports and documentation

- [x] Update README and architecture documentation.
- [x] Add research protocol, Friday meeting pack, demo scripts, supervisor decisions, restart checklist, and known limitations.
- [x] Generate manifest, data dictionary, deterministic demo fixture data, and a static HTML snapshot.

Acceptance criteria:

- Setup, test, demo, and live-pilot commands are exact and safe.
- Documents distinguish implemented, locally validated, technical-pilot ready, and pending work.
- The documented commands and evidence match the validated build.

Validation:

```powershell
rg -n "DEMO FIXTURE - NOT RESEARCH DATA|TECHNICAL PILOT" README.md docs app.py
```

## Milestone 7 - Final QA

- [x] Run formatting/lint checks, compile/import checks, full Pytest, manifest validation, and Streamlit smoke tests.
- [x] Scan tracked-style project files and outputs for secrets.
- [x] Record exact final results and remaining limitations in `STATUS.md`.

Acceptance criteria:

- All mandatory P0 tests pass or a precise blocker and safe workaround is documented.
- The clean-start five-minute demonstration is reproducible offline.

Validation:

```powershell
& .\.venv\Scripts\python.exe -m ruff check app.py src scripts tests
& .\.venv\Scripts\python.exe -m ruff format --check app.py src scripts tests
& .\.venv\Scripts\python.exe -m compileall -q app.py src scripts tests
& .\.venv\Scripts\python.exe -m pytest -q
```
