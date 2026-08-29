# Final Study V2 readiness workflow

Status: prospective infrastructure only. This document is not evidence that a
replacement endpoint was selected, Pilot V6 ran, an approval was granted, or
main-study data were collected.

## Current machine state

The current state remains fail closed:

- replacement catalogue: `NOT_FETCHED`;
- replacement screen: `NOT_RUN`;
- replacement selection: `NOT_SELECTED`;
- Pilot V6: `NOT_CONFIGURED`;
- final active protocol bundle: `NOT_CREATED`;
- Main Study V2: `BLOCKED`.

Run the zero-network state check with:

```powershell
& .\.venv\Scripts\python.exe scripts\check_main_study_readiness.py
```

A non-zero exit is expected while the study is blocked.

## Frozen transition order

The only permitted progression is:

1. retrieve and retain one catalogue response under the guarded catalogue command;
2. apply the versioned zero-price, modality, seed, context and exact-slug policy;
3. screen candidates in the retained deterministic order;
4. require a 12/12, zero-truncation replacement-screen `PASS`;
5. create an append-only replacement-selection record for the first eligible `PASS`;
6. configure Pilot V6 from MiniMax plus that exact selected replacement;
7. run and independently assess Pilot V6;
8. require a 24/24, all-`stop`, zero-truncation Pilot V6 `PASS`;
9. generate the exact final two-model configuration and 72-row manifest;
10. create and verify the new `study-v2.1.0` active protocol bundle;
11. record genuine human governance decisions independently;
12. permit a guarded main-study invocation only when every machine and human gate passes.

No `--force`, fallback, router alias, manually edited verdict, or CLI attestation can
skip a transition.

## Pilot V6

Pilot V6 is `technical-pilot-v6.0.0`. Its prospective subset is the existing
monitoring fixed-belief scenario crossed with both final models and both context
conditions: four conversations and 24 response slots. It uses `generation-v3`,
the frozen 1024-token maximum, repetition-one seed 20260814, a 32-attempt hard cap
and at least five seconds between POST starts.

Successful turns are immutable and skipped on resume. Errors are append-only. A
429 stops the affected conversation for that invocation. `PASS` requires complete,
contiguous evidence, exact requested/resolved model identity, provider metadata,
non-empty private response text, `finish_reason=stop` throughout, zero truncation,
correct requests/configuration and an intact selection binding.

## Historical and active bundles

`protocol/study-v2.0.0` remains historical evidence for the superseded
MiniMax/Nemotron candidate pair. `verify_historical_bundle()` checks only that
historical evidence; it can never authorise collection.

The future `study-v2.1.0` bundle is separate. It cannot be created until replacement
selection and Pilot V6 both recompute to `PASS`. It freezes the exact selected pair,
72-row manifest, generation settings, selection and qualification hashes, scenarios,
histories, draft rubric status, provider/execution policies, runner code and relevant
analysis configuration. Text hashes are line-ending normalised so verification is
stable across supported checkouts.

`verify_active_study_bundle()` checks both bundle integrity and equality with the
current source/configuration used for collection. Missing, stale, tampered or
placeholder material blocks the main study.

## Human governance remains independent

`config/main-study-governance.yaml` records the current pending human decisions.
Technical `PASS` does not imply supervisor, ethics, rubric, annotation/adjudication
or data-management approval. `--confirm-protocol-frozen` is an operator attestation,
not proof that any approval occurred.

## Commands that remain prospective

The scripts expose help and offline defaults now. Future live commands require the
retained evidence paths and all explicit environment/CLI gates. They must not be run
until authorised and until the preceding state transition has passed. The active
bundle creation command also requires `--create --confirm-freeze`; without those
flags it is verification-only and makes no network request.
