# Main Study V2 runbook

1. Resolve every item in `MAIN_STUDY_GO_NO_GO_CHECKLIST.md` and record real approval.
2. Run all offline validation and verify the historical protocol bundle and evidence fingerprints.
3. Confirm immutable Pilot V4 remains FAIL and immutable Pilot V5 remains FAIL; both source
   hashes still verify.
4. Run original-pair Pilot V6 only after separate authorisation and require its
   generation-v4 PASS. Until then the study is blocked by `final_model_pair_not_qualified`.
5. Only if V6 fails, activate replacement-screen v2; a selected replacement requires a new
   future Pilot V7 and must never overwrite V6.
6. Create and verify the exact final study-v2.1.0 active bundle.
7. If approved, execute small manifest-ordered batches and retain each terminal summary.
8. Re-run the audit after each batch. Never delete an error or regenerate a successful turn.
9. After collection, create blinded items using a private blinding key and keep the mapping
   in `data/private/`. Complete human annotation before analysis.

Offline commands:

```powershell
& .\.venv\Scripts\python.exe scripts\audit_pilot_v4.py
& .\.venv\Scripts\python.exe scripts\audit_pilot_v5.py
& .\.venv\Scripts\python.exe scripts\run_pilot_v5.py
& .\.venv\Scripts\python.exe scripts\assess_pilot_v5.py
& .\.venv\Scripts\python.exe scripts\audit_generation_budget.py
& .\.venv\Scripts\python.exe scripts\run_generation_calibration.py
& .\.venv\Scripts\python.exe scripts\run_pilot_v6.py
& .\.venv\Scripts\python.exe scripts\run_study.py
& .\.venv\Scripts\python.exe scripts\audit_study.py
```

Future live commands require separate authorisation and are not part of repository QA.
The V5 assessor is offline and recomputes `FAIL` from immutable evidence; 11 truncated
responses cannot be replaced, so resume cannot become PASS. Study V2 requires the prospective
Pilot V6 and active-bundle evidence chain; an edited assessment file or
confirmation flag cannot bypass the gate. `--confirm-protocol-frozen` is an operator attestation, not proof of
supervisor, ethics, rubric, annotation/adjudication or data-management approval.
