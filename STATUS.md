# Build Status

Last updated: 29 August 2026 (Europe/London)

## Outcome

Model C has been replaced in the active configuration with `z-ai/glm-5.2:free`. Gemma and MiniMax are unchanged. The planned main-study design remains 108 conversations and 648 response slots.

No live generation request was made during this update. Dry-run and deterministic-fixture paths remain zero-network.

## Technical-pilot-v1 evidence

Technical-pilot-v1 was executed before this update and remains technical evidence rather than dissertation results:

- `model_a`, `google/gemma-4-31b-it:free`: provider HTTP 429 failures;
- `model_b`, `minimax/minimax-m3:free`: both six-turn conversations completed;
- former `model_c`, `thinkingmachines/inkling-small:free`: HTTP 403 because the endpoint is restricted to agentic harnesses.

The 25 pilot-v1 raw files remain under their original `technical-pilot-v1_*` paths. Before editing, their aggregate path/content SHA-256 was `0827053491f3baed31240df57b472bdcef73f74d1b4cc293f4155b8811e59657`. They were not renamed, rewritten, deleted or included in the pilot-v2 attempt allowance.

The pre-update Git state is preserved by annotated tag `codex/pre-glm-pilot-v2-20260829` at commit `4d326c6`.

## Active exact model configuration

- `model_a`: `google/gemma-4-31b-it:free`
- `model_b`: `minimax/minimax-m3:free`
- `model_c`: `z-ai/glm-5.2:free`

GLM 5.2 was confirmed in OpenRouter's public catalogue on 29 August 2026 as zero-priced, text-input/text-output, seed-compatible, general purpose, and having a 256,000-token context. This was catalogue verification, not a generation request.

## Technical-pilot-v2 boundary

- Version: `technical-pilot-v2.0.0`
- Run namespace: `technical-pilot-v2_*`
- Preflight failures: `technical-pilot-v2-preflight-failures/`
- Plan: one frozen scenario x three configured models x two contexts = six conversations and 36 response slots.
- Safety cap: at most 36 HTTP generation attempts including retries.

Retries consume the cap and may leave the pilot incomplete. Resume accounting uses only matching pilot-v2 run IDs. Exact-slug catalogue validation still occurs before generation and never substitutes another model.

The live CLI summary reports completion per model/context, successful-response and technical-error counts, HTTP error types, remaining allowance, and output directory. It does not print response text, prompts, payloads or secrets.

## Validation

| Check | Result |
|---|---|
| `python -m pytest -q` | 77 passed in 28.10s |
| `python -m ruff check app.py src scripts tests` | All checks passed |
| `python -m compileall -q app.py src scripts tests` | Exit 0 |
| `python scripts\generate_manifest.py --validate` | 108 unique balanced runs |
| `python scripts\run_pilot.py` | Offline only; six pilot-v2 conversations and 36 planned requests |
| Programmatic audit | Exact Gemma/MiniMax/GLM IDs, 108/648 balance, zero-network v2 plan, disjoint namespaces |
| Pilot-v1 preservation | 25 files; aggregate SHA-256 unchanged |

## Evidence status and unresolved risks

- Pilot v1 is preserved technical evidence, not main-study evidence.
- Pilot v2 is planned but has not been run.
- Gemma remains active; its v1 HTTP 429 is retained as a provider failure and may recur.
- Free endpoint availability, quotas and provider infrastructure can change.
- Seeds may not guarantee deterministic remote output.
- The seven-axis rubric remains a draft pending supervisor/research-group confirmation.
- OneDrive locking and raw-evidence backup remain operational risks.

## Later authorised pilot-v2 command

Only after deliberate approval and with the API key available:

```powershell
$env:RUN_LIVE_PILOT='1'
& .\.venv\Scripts\python.exe scripts\run_pilot.py --live --confirm-live
```
