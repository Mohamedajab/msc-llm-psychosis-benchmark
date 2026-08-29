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

Pilot V5 ran and is now closed as immutable `FAIL`: it completed 24/24 slots but 11 responses
were truncated, so resume cannot become PASS. The versioned qualification assessor recomputes
this `FAIL` from the isolated `technical-pilot-v5.0.0` namespace, fails closed on
integrity/configuration defects, writes append-only content-free records under ignored
`data/raw/pilot-v5-qualification/`, and never trusts a stored verdict without recomputing source
hashes and criteria. Nemotron is rejected as the final comparator on technical
generation-suitability grounds only.

Study V2 now also reads the versioned replacement-pending status and raises
`replacement_endpoint_not_frozen` before provider construction or catalogue access, so no CLI
confirmation flag can bypass it. Its protocol-confirmation flag is an operator attestation and
never represents supervisor or ethics approval.

Length-limited textual completions are observations, with `truncated=true`. Their frequency
is reported and primary findings receive a sensitivity analysis excluding truncated turns.
