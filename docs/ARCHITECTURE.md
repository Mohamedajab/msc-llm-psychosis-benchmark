# Architecture

Versioned JSON/YAML configuration defines scripts, histories, model identities, generation
settings and the frozen rubric. `src/manifest.py` derives the 72-row Study V2 manifest.

`src/payloads.py` builds target-visible history from the optional versioned instruction,
frozen context and conversation turns. Generation-v4's instruction is null, so no artificial
style or length message is inserted.
`src/provider_client.py` performs strict catalogue qualification, documented routing,
pacing, exact resolved-model checks and safe response parsing. `src/conversation_runner.py`
executes six turns, while `src/storage.py` writes immutable headers/successes and append-only
errors. `src/study_execution.py` supplies shared resume and attempt accounting.

`scripts/run_pilot.py` remains the historical Pilot V3 interface using archived config.
`scripts/run_pilot_v4.py` is a closed offline inspection interface tied to archived
generation-v2. `scripts/run_pilot_v5.py` is a closed historical interface bound to archived
generation-v3. Replacement-screen v2 and Pilot V6 prospectively use generation-v4.
`scripts/run_study.py` can execute the final manifest only after original-pair Pilot V6,
active-bundle and genuine readiness gates all pass. Replacement-screen/selection remains a
fallback activated only by V6 failure. All workflows use disjoint private/raw
namespaces and are offline by default.

The protocol bundle hashes all execution-critical planned material. Study audit, blinding,
annotation and trajectory modules reject mixed evidence and produce outputs only from saved
real Study V2 records and human ratings.
