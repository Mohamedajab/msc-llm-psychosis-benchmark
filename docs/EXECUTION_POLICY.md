# Study V2 execution policy

Offline is the default. Pilot V5 is closed and cannot be resumed. Future replacement-screen
v2 and Pilot V6 require their explicit live, confirmation, environment and evidence gates.
The main study additionally requires `--confirm-protocol-frozen`,
`RUN_LIVE_STUDY=1`, an explicit per-invocation HTTP-attempt cap, and a verified bundle.

Successful turns are immutable and resumed in sequence. Errors are append-only. A request
blocked before POST consumes zero HTTP attempts. HTTP 429 is recorded and stops the current
invocation without immediate retry. POST starts are at least five seconds apart. No model
is substituted. Pilot V6 has 24 required responses plus eight bounded failure attempts,
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

Generation-v4 is prospective. Its 4096-token completion limit is an emergency envelope, not
a desired response length. Every model receives the same neutral visible-response contract.
Reasoning remains model-native; the request excludes reasoning traces, and the provider parser
retains only safe reasoning presence/length and token counts when reported. Reasoning text is
never copied into assistant content or annotation material. Missing visible-token usage remains
null rather than being derived from combined completion usage.

Study V2 now also reads the versioned replacement-pending status and raises
`replacement_endpoint_not_frozen` before provider construction or catalogue access, so no CLI
confirmation flag can bypass it. Its protocol-confirmation flag is an operator attestation and
never represents supervisor or ethics approval.

Length-limited textual completions are observations, with `truncated=true`. Their frequency
is reported and primary findings receive a sensitivity analysis excluding truncated turns.
For the reusable benchmark this is a technical outcome. Pilot V6 nevertheless requires all
24 responses to finish with `stop` and zero truncation because incomplete turns can affect
later dialogue in the matched MSc study.
