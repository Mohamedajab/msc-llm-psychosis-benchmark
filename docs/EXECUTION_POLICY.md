# Study V2 execution policy

Offline is the default. Pilot V4 requires `--live`, `--confirm-live`, `RUN_LIVE_PILOT=1`
and an API key. The main study additionally requires `--confirm-protocol-frozen`,
`RUN_LIVE_STUDY=1`, an explicit per-invocation HTTP-attempt cap, and a verified bundle.

Successful turns are immutable and resumed in sequence. Errors are append-only. A request
blocked before POST consumes zero HTTP attempts. HTTP 429 is recorded and stops the current
invocation without immediate retry. POST starts are at least five seconds apart. No model
is substituted. Pilot V4 has 24 required responses plus eight bounded failure attempts,
for a lifetime cap of 32 HTTP attempts.

Length-limited textual completions are observations, with `truncated=true`. Their frequency
is reported and primary findings receive a sensitivity analysis excluding truncated turns.
