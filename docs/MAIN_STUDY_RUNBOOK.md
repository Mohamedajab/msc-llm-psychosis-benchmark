# Main Study V2 runbook

1. Resolve every item in `MAIN_STUDY_GO_NO_GO_CHECKLIST.md` and record real approval.
2. Run all offline validation and verify the historical protocol bundle and evidence fingerprints.
3. Confirm immutable Pilot V4 remains FAIL and immutable Pilot V5 remains FAIL; both source
   hashes still verify.
4. Recompute the preserved original-pair Pilot V6 PASS and verify its source-evidence hash.
5. Keep replacement-screen v2 unused; it was only the fallback if V6 failed.
6. Create and verify the exact final study-v2.1.0 active bundle.
7. If approved, use the Main Study Collection view or guarded command-line batches. Progress
   is reconstructed from append-only evidence; a browser session is not authoritative.
8. Re-run the audit after each batch. Never delete an error or regenerate a successful turn.
9. After collection, create blinded items using a private blinding key and keep the mapping
   in `data/private/`. Complete human annotation before analysis.

## Streamlit collection steps

Start the local app with:

```powershell
& .\.venv\Scripts\python.exe -m streamlit run app.py
```

Open **Main Study Collection**, then:

1. select **Run preflight**;
2. resolve every displayed blocker outside the app;
3. confirm that the frozen collection is being started;
4. select **Start Main Study**.

The app starts one local worker and reads progress from persisted evidence. Closing or
refreshing the browser does not stop or restart the worker. **Stop safely** writes a stop
request that is checked between response requests; an in-progress request is allowed to finish
and save first.

An embedded upstream HTTP 402 is not retried automatically. If it is the only collection block,
the app reconstructs and verifies the first missing request, shows the incident explicitly and
requires the operator to confirm a manual resume. A repeated 402 stops again for review. The
stored error remains in the audit trail and no completed response is replaced.

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
confirmation flag cannot bypass the gate. `--confirm-protocol-frozen` is an operator attestation,
not proof of supervisor review and cannot change the recorded ethics, rubric, annotation or
data-management statuses. Supervisor review is useful provenance but is not a hard collection
gate.
