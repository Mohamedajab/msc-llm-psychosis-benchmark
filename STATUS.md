# Build Status

Last updated: 28 August 2026, 23:50 BST (Europe/London)

## Outcome

The repository now has a minimal configuration-driven three-model OpenRouter integration. No live inference or pilot was run. Dry-run and deterministic-fixture paths remain zero-network and visibly separated from the gated live technical pilot.

The verified pre-edit state is preserved by annotated tag `codex/pre-openrouter-three-model-integration-20260828` at commit `043ff25`.

## Exact target models

One read-only request to `https://openrouter.ai/api/v1/models` was made on 28 August 2026. It confirmed these exact zero-priced text-input/text-output endpoints with seed support and sufficient context:

- `google/gemma-4-31b-it:free` — Google DeepMind instruction-tuned family; 262,144-token context.
- `minimax/minimax-m3:free` — MiniMax general multimodal foundation family; 1,048,576-token context.
- `thinkingmachines/inkling-small:free` — Thinking Machines general-purpose family; 1,048,576-token context.

The IDs are versioned in `config/models.yaml`. Routers, `latest` aliases, paid endpoints and silent substitution are rejected.

## Experiment accounting

- Main study: `3 presentations x 3 themes x 3 models x 2 contexts x 2 repetitions = 108 conversations`.
- Planned main-study responses: `108 x 6 = 648`.
- Technical pilot: `1 frozen scenario x 3 models x 2 contexts = 6 conversations`.
- Pilot cap: at most 36 HTTP generation attempts including retries, reconstructed from append-only records on resume.

Every later request retains the frozen context condition, all earlier user messages, all assistant responses verbatim, and the current user message. Requested/returned identity, run ID, turn, repetition, seed/parameters, timestamps, latency, usage, payload hash, and error/retry details remain stored in provenance.

## Safety gates

Live execution requires all four conditions:

1. explicit live mode or `--live`;
2. `RUN_LIVE_PILOT=1`;
3. `OPENROUTER_API_KEY` available to the process;
4. final on-screen confirmation or `--confirm-live`.

All exact IDs are checked from one catalogue response before generation. A failed preflight creates a technical-failure record and makes no generation request. Provider errors are never saved as chatbot responses.

## Final validation

All commands used `C:\Users\Moham\OneDrive\Documents\project\.venv\Scripts\python.exe`.

| Validation | Result |
|---|---|
| `python -m pytest -q` | 76 passed in 18.31s |
| `python -m ruff check app.py src scripts tests` | All checks passed |
| `python -m compileall -q app.py src scripts tests` | Exit 0 |
| `python scripts\generate_manifest.py --validate` | 108 unique balanced runs |
| `python scripts\run_pilot.py` | Offline only; 6 conversations; maximum 36 generation attempts |
| Programmatic design audit | 3 exact IDs, 108 unique runs, 648 response slots, balanced cells, distinct seeds, complete later-turn history, zero-network pilot |

## Current evidence status and unresolved risks

- Demo fixtures are **DEMO FIXTURE - NOT RESEARCH DATA**.
- The technical pilot remains unexecuted and **TECHNICAL PILOT - DESCRIPTIVE ONLY**.
- The 108-row main-study manifest is a plan; the main study has not run.
- Free endpoint availability, quotas and provider infrastructure can change; same-time preflight may therefore stop collection.
- A remote provider may not honour a seed deterministically, and infrastructure behind an unchanged slug may change.
- The seven-axis rubric remains a draft pending supervisor/research-group confirmation.
- OneDrive conflict/locking and raw-evidence backup procedures remain operational risks.

## Deliberately authorised live command

Only after approval and with the API key available:

```powershell
$env:RUN_LIVE_PILOT='1'
& .\.venv\Scripts\python.exe scripts\run_pilot.py --live --confirm-live
```
