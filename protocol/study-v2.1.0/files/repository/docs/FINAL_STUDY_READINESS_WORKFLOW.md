# Final Study V2 readiness workflow

Status: Pilot V6 passed. No replacement endpoint was selected, no approval is inferred, and no
main-study data have been collected.

## Current machine state

The current state remains fail closed:

- replacement catalogue: `NOT_FETCHED`;
- replacement screen: `NOT_RUN`;
- replacement selection: `NOT_SELECTED`;
- Pilot V6: `PASS`;
- final pair: `QUALIFIED` from `ORIGINAL_PAIR_V6`;
- replacement required: `false`;
- final active protocol bundle: `NOT_CREATED`;
- Main Study V2: `BLOCKED`.

Run the zero-network state check with:

```powershell
& .\.venv\Scripts\python.exe scripts\check_main_study_readiness.py
```

A non-zero exit is expected while the study is blocked.

## Primary and fallback transition order

The primary progression is:

1. preserve and recompute the 24/24, all-`stop`, zero-truncation Pilot V6 `PASS`;
2. freeze `final_pair_source=ORIGINAL_PAIR_V6` for MiniMax plus Nemotron;
3. generate the exact final two-model configuration and 72-row manifest;
4. create and verify the new `study-v2.1.0` active protocol bundle;
5. retain the ethics determination and method-readiness decisions, and record supervisor review
   when it is available;
6. permit a guarded main-study invocation only when every genuine readiness gate passes.

If and only if original-pair Pilot V6 returns `FAIL`, `replacement_required=true` activates
the retained fallback: guarded catalogue evidence, replacement-screen v2, deterministic
selection, and a separately versioned future Pilot V7 for the replacement pair. V6 is never
overwritten or reused. Pilot V7 is a prospective rule, not implemented or run here.

No `--force`, fallback, router alias, manually edited verdict, or CLI attestation can
skip a transition.

## Pilot V6

Pilot V6 is `technical-pilot-v6.0.0`. It requalifies the intended original MiniMax/Nemotron
pair. Its prospective subset is the existing monitoring fixed-belief scenario crossed with both
models and both context
conditions: four conversations and 24 response slots. It uses `generation-v4`,
no additional visible-response style instruction, the model-native reasoning policy, a
4096-token non-binding emergency
envelope, repetition-one seed 20260814, a 32-attempt hard cap
and at least five seconds between POST starts.

Successful turns are immutable and skipped on resume. Errors are append-only. A
429 stops the affected conversation for that invocation. `PASS` requires complete,
contiguous evidence, exact requested/resolved model identity, provider metadata,
non-empty private response text, `finish_reason=stop` throughout, zero truncation,
correct requests/configuration and intact original-pair provenance. Replacement selection is
not a Pilot V6 prerequisite.

## Historical and active bundles

`protocol/study-v2.0.0` remains historical evidence for the superseded
MiniMax/Nemotron candidate pair. `verify_historical_bundle()` checks only that
historical evidence; it can never authorise collection.

The future `study-v2.1.0` bundle is separate. On the primary path it cannot be created until
original-pair Pilot V6 recomputes to `PASS`. It freezes
`final_pair_source=ORIGINAL_PAIR_V6`, the exact pair, 72-row manifest, complete generation-v4
profile and hash, qualification hash, scenarios,
histories, frozen rubric status, provider/execution policies, runner code and relevant
analysis configuration. Text hashes are line-ending normalised so verification is
stable across supported checkouts.

`verify_active_study_bundle()` checks both bundle integrity and equality with the
current source/configuration used for collection. Missing, stale, tampered or
placeholder material blocks the main study.

## Governance record

`config/main-study-governance.yaml` records the current readiness decisions. The rubric and
annotation procedure are frozen, and data-management arrangements are confirmed in
`DATA_MANAGEMENT.md`. The completed Loughborough University Ethics Awareness Form, with student
declaration dated 25 June 2026 and supervisor declaration dated 19 June 2026, records the route
outcome `No further ethical review required`; this is represented as
`NO_FURTHER_REVIEW_REQUIRED`, not as favourable review or LEON approval.

Supervisor review of the final Study V2 protocol remains useful governance provenance and is
recorded when available. The repository contains no evidence that it is a separate institutional
precondition for this synthetic, no-human-participant study, so `PENDING` is informational and
does not block collection. It must not be misrepresented as confirmed. The
`--confirm-protocol-frozen` flag remains an operator attestation, not evidence of supervisor
review or an ethics determination.

## Commands that remain prospective

The scripts expose help and offline defaults now. Future live commands require the
retained evidence paths and all explicit environment/CLI gates. They must not be run
until authorised and until the preceding state transition has passed. The active
bundle creation command also requires `--create --confirm-freeze`; without those
flags it is verification-only and makes no network request.
