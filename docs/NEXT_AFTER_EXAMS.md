# Restart Plan After Exams

This sequence is designed to restart the dissertation without treating the Friday build or a small technical pilot as completed research.

## Phase 1 — Re-establish a clean, reproducible workspace

1. Open the repository and read `STATUS.md`, `PLAN.md`, this file and the supervisor decision log.
2. Confirm that `research_methods_analysis/` and all source material remain preserved.
3. Use 64-bit Python 3.12 and rebuild `.venv` from `requirements.txt` if its interpreter/package ABI is uncertain.
4. Run the full offline validation suite:

```powershell
cd "C:\Users\Moham\OneDrive\Documents\project"
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe scripts\generate_manifest.py --validate
& .\.venv\Scripts\python.exe scripts\generate_data_dictionary.py
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe -m ruff check app.py src scripts tests
& .\.venv\Scripts\python.exe -m ruff format --check app.py src scripts tests
& .\.venv\Scripts\python.exe -m compileall -q app.py src scripts tests
```

5. Resolve every failure before changing the protocol. Record commands and outcomes honestly in `STATUS.md`.

## Phase 2 — Close supervisor decisions

Use [DECISIONS_FOR_SUPERVISOR.md](DECISIONS_FOR_SUPERVISOR.md). In particular:

- freeze title, aim and research questions;
- obtain the authoritative detailed rubric definitions/anchors, or formally approve a revised version;
- confirm primary axes and threshold/trajectory definitions;
- review all nine scripts and all three prefixes for safety, parallelism and construct validity;
- agree annotator count, training, re-rating fraction/delay, adjudication and wellbeing process;
- confirm ethics/governance and provider-terms requirements;
- agree the endpoint selection/snapshot rule and whether model versions are suitable.

Do not generate main-study outputs while any decision would materially change prompts, models, conditions or labels.

## Phase 3 — Freeze protocol v1

1. Increment versions for every configuration revised after the Friday review.
2. Verify no target message contains condition labels, diagnosis/rubric wording or desired-response cues.
3. Record exact model slugs and the catalogue-check timestamp; do not use an auto-router or moving alias.
4. Freeze generation settings and record whether the provider actually supports the configured seed.
5. Regenerate the 108-row manifest and configuration hashes.
6. Archive a read-only protocol bundle containing configuration, manifest, data dictionary and software revision identifier.
7. Define in writing how model unavailability, provider outages, blocks and partial runs will be handled.

Acceptance criterion: another researcher can identify every planned request from the frozen bundle without seeing any model response.

## Phase 4 — Run only the bounded technical pilot

First inspect the offline plan:

```powershell
& .\.venv\Scripts\python.exe scripts\run_pilot.py
```

If and only if authorised, credentials exist, exact slugs pass the current catalogue check and the explicit live gate is intentional:

```powershell
$env:RUN_LIVE_PILOT='1'
& .\.venv\Scripts\python.exe scripts\run_pilot.py --live --confirm-live
```

Pilot v2 is fixed at six conversations and at most 36 HTTP generation attempts including retries. Every retry consumes the cap, so the pilot may end incomplete. Do not expand it during execution. Resume only matching `technical-pilot-v2_*` runs; never reuse or alter pilot-v1 records.

Afterward, perform a turn-by-turn audit:

- correct run/status label (`technical_pilot`);
- all earlier exchanges present in every later request;
- prefix present only in the standardised condition;
- no system/evaluation cue;
- requested/resolved model IDs match;
- successful response text and metadata retained;
- errors typed correctly and not annotated as responses;
- no secret present in files/logs;
- all partial runs resume without duplicated success files.

Repair software defects and repeat only the smallest necessary technical check. Never silently replace failed pilot evidence.

## Phase 5 — Pilot human annotation

1. Prepare blinded items and store the re-identification map in a separate restricted location.
2. Train annotators on a small fixture/development set that is not used as main evidence.
3. Discuss difficult examples and revise the codebook only before freezing the annotation version.
4. Annotate a small agreed pilot subset independently where feasible.
5. Select the prespecified re-rating sample under new opaque IDs after the agreed delay.
6. Report exact agreement and linearly weighted kappa per axis.
7. Call it intra-rater reliability for one annotator; reserve inter-rater for two independent annotators.
8. Examine disagreements and uncertainty flags without changing raw ratings.

If agreement or interpretability is poor, revise the rubric/codebook, increment its version, retrain and repeat a development exercise before main annotation.

## Phase 6 — Authorise and execute the main study

Only proceed after the protocol, ethics/governance position, budget/quota and annotation process are signed off.

1. Back up the frozen bundle and empty main-study raw-data destination.
2. Recheck exact endpoint availability immediately before starting.
3. Execute manifest rows in their seeded order, retaining status/error fields.
4. Monitor quota/rate behaviour without changing prompts or substituting models.
5. Resume partial rows; do not rerun successful turns.
6. Stop and document a protocol deviation if an endpoint disappears or resolves differently.
7. At completion, reconcile 108 planned rows against completed, partial, failed and missing observations.
8. Create a read-only backup of raw run directories before annotation/analysis.

Do not label the dataset complete merely because 648 responses were planned. Completeness is based on valid stored response observations and explicitly reported missingness.

## Phase 7 — Main annotation and reliability

1. Randomise/blind item presentation using the frozen procedure.
2. Keep annotation event logs append-only.
3. Monitor progress and missing axes without exposing experimental identity.
4. Preserve notes and uncertainty/adjudication flags.
5. Complete the prespecified reliability subset.
6. Resolve adjudication using the agreed rule while preserving original annotator events.
7. Export a tidy blinded table, then join experimental metadata only in the analysis environment.
8. Document exclusions and version mismatches before looking at condition comparisons.

## Phase 8 — Prespecified analysis

1. Start with data quality, status counts and missingness.
2. Show A1, A2 and A3 separately as primary outcomes.
3. Report exploratory B/C axes separately and visibly label them exploratory.
4. Build one row per conversation before comparisons or bootstrap.
5. Report onset, persistence, recovery and final-turn measures using frozen definitions.
6. Use matched model/context comparisons and show unmatched counts.
7. Resample whole conversations/matched pairs or script clusters, never turns.
8. Present lexical/TF-IDF features as exploratory wording signals with limitations.
9. Activate the grouped supervised baseline only if minimum class/conversation requirements are met; keep it secondary.
10. Do not choose plots/outcomes based only on which comparison looks strongest.

## Phase 9 — Dissertation evidence pack

Preserve:

- final protocol and deviations;
- configuration files and content hashes;
- manifest and execution status;
- software revision and dependency specification;
- raw-to-derived data dictionary;
- annotation codebook, training and reliability report;
- missingness and provider error audit;
- analysis scripts/notebooks and fixed seeds;
- generated tables/figures with status labels;
- limitations and decisions log.

Write claims at the correct scope: selected endpoint/configuration, selected synthetic scripts and collection date. Do not generalise to all language models or to people with psychosis, and do not infer clinical causation.

## Three first actions on the restart day

1. Rebuild/verify the Python 3.12 environment and run the complete offline QA suite.
2. Convert the supervisor's meeting notes into explicit rubric/script/RQ decisions and version changes.
3. Generate and inspect the zero-network technical-pilot plan; do not enable live mode until its approval checklist is complete.
