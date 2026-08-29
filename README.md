# MSc LLM psychosis benchmark

An auditable, configuration-driven benchmark of how two exact language-model endpoints
respond across six-turn conversations containing controlled unsupported interpretations.
No main-study data or results currently exist.

## Frozen Study V2 design

Study `study-v2.0.0` crosses three presentation levels, three themes, two models, two
context conditions and two repetitions: 72 conversations and 432 planned responses.

- `minimax/minimax-m3:free`
- `nvidia/nemotron-3-super-120b-a12b:free`

The reduction from the historical 108-conversation plan was adopted before data collection
and is documented in `docs/PROTOCOL_DEVIATION_STUDY_V2.md`. Active generation-v3 uses 1024
output tokens and the unchanged frozen repetition seeds 20260814/20260815.

## Evidence boundaries

Demo fixtures, Pilot V1, Pilot V2, Pilot V3, the Nemotron endpoint screen, failed Pilot V4,
planned Pilot V5, and the main study are distinct namespaces. Technical evidence is not
dissertation data. Pilot V1-V4 and the screen are immutable. Raw responses, assessments,
annotations, private maps and credentials are ignored by Git.

## Offline validation

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m ruff check app.py src scripts tests
& .\.venv\Scripts\python.exe -m ruff format --check app.py src scripts tests
& .\.venv\Scripts\python.exe scripts\generate_manifest.py --validate
& .\.venv\Scripts\python.exe scripts\audit_pilot_v4.py
& .\.venv\Scripts\python.exe scripts\audit_pilot_v5.py
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

As a result, NVIDIA Nemotron Super is rejected as the proposed final Study V2 comparator on
technical generation-suitability grounds only. MiniMax M3 remains technically qualified based
on its completed pilot behaviour. The replacement endpoint is `NOT_SELECTED`, Pilot V6 is
`NOT_CONFIGURED`, and the main study is `BLOCKED` by the `replacement_endpoint_not_frozen`
blocker. The 72-conversation factorial structure is unchanged but cannot be refrozen around a
replacement endpoint until one passes prospective technical screening.

The Study V2 live runner recomputes the V4 and V5 assessments from immutable evidence and
checks the versioned replacement-pending status before it can construct a live provider. A
future PASS is technical qualification only, not academic approval.

See `docs/MAIN_STUDY_RUNBOOK.md`, `docs/RESEARCH_PROTOCOL.md` and
`docs/MAIN_STUDY_GO_NO_GO_CHECKLIST.md` before any collection.
