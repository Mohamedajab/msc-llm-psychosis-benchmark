# Known limitations and validity threats

- Two free OpenRouter endpoints do not represent all models or clinical populations.
- Free availability, rate limits and provider routing can change during collection.
- Exact model identity does not guarantee identical backend infrastructure; provider
  distributions and changes must be reported and described or stratified as a possible
  implementation confound.
- Pilot V4 established endpoint accessibility but failed generation suitability: all 12
  Nemotron responses reached the archived 512-token cap.
- Pilot V5 ran under generation-v3's 1024-token cap and completed 24/24 slots, but 11
  Nemotron/Nvidia responses were still truncated, so Pilot V5 is closed as immutable FAIL.
  Nemotron failed the frozen generation-v2/v3 qualification; this does not establish intrinsic
  unsuitability under every possible future benchmark configuration.
- V4/V5 did not retain reported reasoning-token usage, so reasoning's contribution to those
  exact historical responses cannot be quantified. A benign calibration supports a material
  contribution under the tested current route, but it is not a replay of the research prompts
  and does not establish sole causation.
- Generation-v4's 4096-token envelope was the smallest tested native-reasoning condition that
  stopped in the benign calibration. It reduces technical truncation risk but may increase
  latency and annotation burden because response length is deliberately not constrained. The
  120-second timeout reduces avoidable timeout censoring while retaining latency as telemetry.
- Model-native reasoning is not identical internal computation across endpoints. The benchmark
  standardises experimental inputs and records reasoning controls/usage where available; it
  cannot make proprietary internal processes equivalent.
- The original pair passed Pilot V6 under generation-v4, but that small technical pilot does not
  establish behavioural validity or replace active-bundle and collection-time integrity checks.
- Fixed scripts improve control but reduce ecological validity and conversational diversity.
- The standardised history is synthetic and may not generalise to organic prior dialogue.
- Rubric v1.0.0 and its annotation procedure are frozen, but human rating remains subjective,
  including the binary A3 judgement and decisions about when A2/A3 are not applicable.
- Two repetitions estimate limited stochastic variation and are not independent populations.
- Conversation/script-cluster analyses support benchmark claims only, not diagnosis, causality,
  prevalence, patient outcomes or population-wide safety claims.
