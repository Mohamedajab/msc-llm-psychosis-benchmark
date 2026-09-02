# Supplementary LLM judges

The `LLM Judges` page applies the frozen rubric in `config/rubric.yaml` to the 432 blinded
main-study responses. Human annotation remains primary. Judge ratings are stored separately under
`data/private/judges/` and are not copied into the human annotation log.

The frozen judge configuration is `config/llm-judges.yaml`:

- DeepSeek V4 Pro and DeepSeek V4 Flash use the direct DeepSeek API.
- GLM-5.3-Flash uses OpenRouter.
- All requests use low-variance JSON output with a short completion limit.
- No target model, provider, experimental condition, repetition or human rating is included.

Each successful judgement is written immediately to its judge's `successes` directory. The file is
immutable, so normal resume skips it. Failed attempts are retained separately in `errors`. A safe
stop prevents new requests from starting while allowing in-flight requests to finish and save.

The offline preflight command is:

```powershell
& .\.venv\Scripts\python.exe scripts\run_judges.py
```

Live collection requires both `--live` and `--confirm-live`, plus `RUN_LIVE_JUDGES=1`. The two
DeepSeek judges read `DEEPSEEK_API_KEY`; GLM reads `OPENROUTER_API_KEY`. Keys are never written to
judge evidence or terminal summaries.
