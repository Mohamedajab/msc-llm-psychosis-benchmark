# Study V2 execution policy

Offline is the default. Pilot V5 requires `--live`, `--confirm-live`, `RUN_LIVE_PILOT=1`
and an API key. The main study additionally requires `--confirm-protocol-frozen`,
`RUN_LIVE_STUDY=1`, an explicit per-invocation HTTP-attempt cap, and a verified bundle.

Successful turns are immutable and resumed in sequence. Errors are append-only. A request
blocked before POST consumes zero HTTP attempts. HTTP 429 is recorded and stops the current
invocation without immediate retry. POST starts are at least five seconds apart. No model
is substituted. Pilot V5 has 24 required responses plus eight bounded failure attempts,
for a lifetime cap of 32 HTTP attempts.

Pilot V4 is archived as completed but failed generation-v2 technical evidence and its live
path is closed. Its remaining eight nominal attempts cannot replace immutable truncated
success records; no missing slots remain and resume would perform no useful work.

Pilot V5's terminal success status requires the versioned qualification assessor to return
PASS; four nominally completed conversations are insufficient. The assessor reads only the
`technical-pilot-v5.0.0` namespace, fails closed on integrity/configuration defects, writes
append-only content-free records under ignored `data/raw/pilot-v5-qualification/`, and never
trusts a stored verdict without recomputing source hashes and criteria. Study V2 performs
this recomputation before provider construction or catalogue access. Its protocol-confirmation
flag is an operator attestation and never represents supervisor or ethics approval.

Length-limited textual completions are observations, with `truncated=true`. Their frequency
is reported and primary findings receive a sensitivity analysis excluding truncated turns.
