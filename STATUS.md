# Build Status

Last updated: 29 August 2026 (Europe/London)

## Outcome

Technical-pilot-v3 now has a separate, resumable execution policy. Gemma, MiniMax and GLM 5.2 are unchanged. The planned main-study design remains 108 conversations and 648 response slots.

No live generation request was made during this update. Dry-run and deterministic-fixture paths remain zero-network.

## Technical-pilot-v1 evidence

Technical-pilot-v1 was executed before this update and remains technical evidence rather than dissertation results:

- `model_a`, `google/gemma-4-31b-it:free`: provider HTTP 429 failures;
- `model_b`, `minimax/minimax-m3:free`: both six-turn conversations completed;
- former `model_c`, `thinkingmachines/inkling-small:free`: HTTP 403 because the endpoint is restricted to agentic harnesses.

The 25 pilot-v1 raw files remain under their original `technical-pilot-v1_*` paths. Before editing, their aggregate path/content SHA-256 was `0827053491f3baed31240df57b472bdcef73f74d1b4cc293f4155b8811e59657`. They were not renamed, rewritten, deleted or included in the pilot-v2 attempt allowance.

The pre-update Git state is preserved by annotated tag `codex/pre-glm-pilot-v2-20260829` at commit `4d326c6`.
The pre-v3-policy Git state is preserved by tag `codex/pre-pilot-v3-policy-20260829` at commit `c297335`.

## Active exact model configuration

- `model_a`: `google/gemma-4-31b-it:free`
- `model_b`: `minimax/minimax-m3:free`
- `model_c`: `z-ai/glm-5.2:free`

GLM 5.2 was confirmed in OpenRouter's public catalogue on 29 August 2026 as zero-priced, text-input/text-output, seed-compatible, general purpose, and having a 256,000-token context. This was catalogue verification, not a generation request.

## Technical-pilot-v2 evidence

Pilot v2 remains immutable technical evidence:

- MiniMax completed both conversations with 12 successful responses.
- Gemma returned HTTP 429 in both contexts with `retry_count=3` each.
- GLM standard context returned HTTP 429 with `retry_count=3`.
- GLM no-context returned HTTP 200 with blank assistant content and `retry_count=1`.
- 26 of 36 attempts were consumed, leaving 10 attempts for 24 required responses; completion was mathematically impossible within the remaining allowance.

The 22 pilot-v2 raw files remain under their original paths. Before the v3 update, their aggregate path/content SHA-256 was `4f8567dd1737406d7ee647bec30ce398bde873c88820758338fd130977e10063`.

## Technical-pilot-v3 boundary

- Version: `technical-pilot-v3.0.0`
- Run namespace: `technical-pilot-v3_*`
- Preflight failures: `technical-pilot-v3-preflight-failures/`
- Plan: one frozen scenario x three configured models x two contexts = six conversations and 36 successful response slots.
- Safety cap: 48 HTTP attempts, comprising 36 required responses plus 12 bounded failures.
- Pacing: configurable, never less than five seconds between live request starts.
- HTTP 429: append once and stop that conversation until a later deliberate invocation; no immediate retry.

Successful turns are loaded and never regenerated or overwritten. A later invocation retries the first missing turn and retains every earlier failure event append-only. Resume accounting uses only matching pilot-v3 run IDs. Exact-slug catalogue validation still occurs before generation and never substitutes another model.

The live CLI summary reports completion per model/context, successful-response and technical-error counts, HTTP error types, remaining allowance, whether that allowance is mathematically sufficient, and output directory. It does not print response text, prompts, payloads, hidden reasoning or secrets.

## Validation

| Check | Result |
|---|---|
| `python -m pytest -q` | 83 passed in 23.08s |
| `python -m ruff check app.py src scripts tests` | All checks passed |
| `python -m compileall -q app.py src scripts tests` | Exit 0 |
| `python scripts\generate_manifest.py --validate` | 108 unique balanced runs |
| `python scripts\run_pilot.py` | Offline only; six pilot-v3 conversations, 36 planned responses and maximum 48 attempts |
| Programmatic audit | Exact Gemma/MiniMax/GLM IDs, 108/648 balance, zero-network v3 plan, disjoint namespaces |
| Pilot-v1 preservation | 25 files; aggregate SHA-256 unchanged |
| Pilot-v2 preservation | 22 files; aggregate SHA-256 unchanged |

## Evidence status and unresolved risks

- Pilot v1 and pilot v2 are preserved technical evidence, not main-study evidence.
- Pilot v3 is planned but has not been run.
- Gemma remains active; its v1 HTTP 429 is retained as a provider failure and may recur.
- Free endpoint availability, quotas and provider infrastructure can change.
- Seeds may not guarantee deterministic remote output.
- The seven-axis rubric remains a draft pending supervisor/research-group confirmation.
- OneDrive locking and raw-evidence backup remain operational risks.

## Later authorised pilot-v3 command

Only after deliberate approval and with the API key available:

```powershell
$env:RUN_LIVE_PILOT='1'
& .\.venv\Scripts\python.exe scripts\run_pilot.py --live --confirm-live --request-interval-seconds 5
```
