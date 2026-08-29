# Known limitations and validity threats

- Two free OpenRouter endpoints do not represent all models or clinical populations.
- Free availability, rate limits and provider routing can change during collection.
- Exact model identity does not guarantee identical backend infrastructure; provider
  distributions and changes must be reported.
- Pilot V4 established endpoint accessibility but failed generation suitability: all 12
  Nemotron responses reached the archived 512-token cap.
- Pilot V5 ran under generation-v3's 1024-token cap and completed 24/24 slots, but 11
  Nemotron/Nvidia responses were still truncated, so Pilot V5 is closed as immutable FAIL.
  Nemotron is rejected as the final comparator on technical generation-suitability grounds only.
- A replacement endpoint has not yet been selected; its screening must return zero truncations
  before the 72-conversation design can be refrozen.
- Fixed scripts improve control but reduce ecological validity and conversational diversity.
- The standardised history is synthetic and may not generalise to organic prior dialogue.
- The draft rubric requires academic review; human ordinal judgement remains subjective.
- Two repetitions estimate limited stochastic variation and are not independent populations.
- Conversation/script-cluster analyses support benchmark claims only, not diagnosis, causality,
  prevalence, patient outcomes or population-wide safety claims.
