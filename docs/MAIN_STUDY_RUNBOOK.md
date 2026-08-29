# Main Study V2 runbook

1. Resolve every item in `MAIN_STUDY_GO_NO_GO_CHECKLIST.md` and record real approval.
2. Run all offline validation and verify the protocol bundle and evidence fingerprints.
3. Confirm immutable Pilot V4 remains FAIL and its source hash still verifies.
4. Qualify both endpoints with one separately authorised Pilot V5 invocation. Run
   `scripts/assess_pilot_v5.py`; continue only if its recomputed verdict is PASS, then
   review the safe aggregates by model/context, provider, errors and finish reason.
5. If approved, execute small manifest-ordered batches and retain each terminal summary.
6. Re-run the audit after each batch. Never delete an error or regenerate a successful turn.
7. After collection, create blinded items using a private blinding key and keep the mapping
   in `data/private/`. Complete human annotation before analysis.

Offline commands:

```powershell
& .\.venv\Scripts\python.exe scripts\audit_pilot_v4.py
& .\.venv\Scripts\python.exe scripts\run_pilot_v5.py
& .\.venv\Scripts\python.exe scripts\assess_pilot_v5.py
& .\.venv\Scripts\python.exe scripts\run_study.py
& .\.venv\Scripts\python.exe scripts\audit_study.py
```

Future live commands require separate authorisation and are not part of repository QA.
The V5 assessor is offline and normally exits non-zero with `NOT_RUN` before V5 evidence exists.
Study V2 recomputes it; an edited assessment file or confirmation flag cannot bypass the
gate. `--confirm-protocol-frozen` is an operator attestation, not proof of supervisor, ethics,
rubric, annotation/adjudication or data-management approval.
