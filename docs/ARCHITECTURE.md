# Architecture

Versioned JSON/YAML configuration defines scripts, histories, model identities, generation
settings and the draft rubric. `src/manifest.py` derives the 72-row Study V2 manifest.

`src/payloads.py` builds target-visible history with the one frozen neutral generation-v4
response instruction and no evaluation cue.
`src/provider_client.py` performs strict catalogue qualification, documented routing,
pacing, exact resolved-model checks and safe response parsing. `src/conversation_runner.py`
executes six turns, while `src/storage.py` writes immutable headers/successes and append-only
errors. `src/study_execution.py` supplies shared resume and attempt accounting.

`scripts/run_pilot.py` remains the historical Pilot V3 interface using archived config.
`scripts/run_pilot_v4.py` is a closed offline inspection interface tied to archived
generation-v2. `scripts/run_pilot_v5.py` is a closed historical interface bound to archived
generation-v3. Replacement-screen v2 and Pilot V6 prospectively use generation-v4.
`scripts/run_study.py` can execute the final manifest only after replacement-screen/selection,
Pilot V6, active-bundle and human-governance gates all pass. All use disjoint private/raw
namespaces and are offline by default.

The protocol bundle hashes all execution-critical planned material. Study audit, blinding,
annotation and trajectory modules reject mixed evidence and produce outputs only from saved
real Study V2 records and human ratings.
