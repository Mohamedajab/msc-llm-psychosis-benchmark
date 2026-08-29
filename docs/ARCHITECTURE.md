# Architecture

Versioned JSON/YAML configuration defines scripts, histories, model identities, generation
settings and the draft rubric. `src/manifest.py` derives the 72-row Study V2 manifest.

`src/payloads.py` builds target-visible history without system/evaluation cues.
`src/provider_client.py` performs strict catalogue qualification, documented routing,
pacing, exact resolved-model checks and safe response parsing. `src/conversation_runner.py`
executes six turns, while `src/storage.py` writes immutable headers/successes and append-only
errors. `src/study_execution.py` supplies shared resume and attempt accounting.

`scripts/run_pilot.py` remains the historical Pilot V3 interface using archived config.
`scripts/run_pilot_v4.py` qualifies the two Study V2 candidates. `scripts/run_study.py`
executes the frozen manifest in order. All are offline by default and use disjoint raw
namespaces.

The protocol bundle hashes all execution-critical planned material. Study audit, blinding,
annotation and trajectory modules reject mixed evidence and produce outputs only from saved
real Study V2 records and human ratings.
