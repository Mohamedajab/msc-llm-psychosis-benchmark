# Study V2 execution policy

Offline is the default. Pilot V5 is closed and cannot be resumed. Pilot V6 passed under its
explicit live, confirmation, environment and evidence gates. Any future replacement screen
retains its own gates. The main study additionally requires `--confirm-protocol-frozen`,
`RUN_LIVE_STUDY=1`, a bounded HTTP-attempt allowance, and a verified active bundle.

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
hashes and criteria. Nemotron failed the frozen generation-v2/v3 qualification; the subsequent
calibration does not retroactively alter the verdicts or the governed replacement decision.

Generation-v4 is prospective. Its 4096-token completion limit is a non-binding emergency
envelope for the intended pair, not a desired response length or universal fairness rule. No
additional target-facing style or length instruction is injected.
Reasoning remains model-native; the request excludes reasoning traces, and the provider parser
retains only safe reasoning presence/length and token counts when reported. Reasoning text is
never copied into assistant content or annotation material. Missing visible-token usage remains
null rather than being derived from combined completion usage.

Study V2 recomputes the Pilot V6 PASS before provider construction or catalogue access. The
Streamlit worker adds bounded automatic resume for recorded transient failures, but never
replaces a successful response. It waits 30, 60 and then at most 120 seconds between resume
cycles, with five consecutive cycles allowed. Truncation, model mismatch, malformed evidence,
non-retryable errors and exhausted limits block collection. The protocol-confirmation flag is
an operator attestation and never records supervisor review or changes the recorded ethics
determination. Supervisor review remains informational provenance rather than a hard execution
gate.

Length-limited textual completions are immutable observations, with `truncated=true`. The first
truncated response is persisted, the trajectory closes immediately, and resume cannot generate
or replace downstream turns. The truncated turn is excluded from primary behavioural
annotation; historical downstream responses, if present, remain excluded as a fail-safe. Lost
behavioural coverage is reported by model and condition rather than handled only as an optional
sensitivity analysis. Pilot V6 nevertheless requires all 24 responses to finish with `stop` and
zero truncation because incomplete turns can affect later dialogue in the matched MSc study.
