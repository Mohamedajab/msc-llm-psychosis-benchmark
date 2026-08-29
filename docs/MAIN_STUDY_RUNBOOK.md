# Main Study V2 runbook

1. Resolve every item in `MAIN_STUDY_GO_NO_GO_CHECKLIST.md` and record real approval.
2. Run all offline validation and verify the protocol bundle and evidence fingerprints.
3. Qualify both endpoints with one separately authorised Pilot V4 invocation.
4. Run `scripts/assess_pilot_v4.py`. Continue only if its recomputed verdict is PASS, then
   review the safe aggregates by model/context, provider, errors and finish reason.
5. If approved, execute small manifest-ordered batches and retain each terminal summary.
6. Re-run the audit after each batch. Never delete an error or regenerate a successful turn.
7. After collection, create blinded items using a private blinding key and keep the mapping
   in `data/private/`. Complete human annotation before analysis.

Offline commands:

```powershell
& .\.venv\Scripts\python.exe scripts\run_pilot_v4.py
& .\.venv\Scripts\python.exe scripts\assess_pilot_v4.py
& .\.venv\Scripts\python.exe scripts\run_study.py
& .\.venv\Scripts\python.exe scripts\audit_study.py
```

Future live commands require separate authorisation and are not part of repository QA.
The assessor is offline and normally exits non-zero with `NOT_RUN` before V4 evidence exists.
Study V2 recomputes it; an edited assessment file or confirmation flag cannot bypass the
gate. `--confirm-protocol-frozen` is an operator attestation, not proof of supervisor, ethics,
rubric, annotation/adjudication or data-management approval.
