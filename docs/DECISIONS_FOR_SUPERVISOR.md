# Decisions requiring supervisor/research-group input

## Required before main collection

- Approve or revise the pre-main-study change from three models/108 conversations to the
  two exact endpoints/72 conversations in Study V2.
- Approve or revise the draft A1-A3 primary and B1-B3/C1 exploratory rubric anchors.
- Confirm annotation staffing, adjudication, rerating proportion and reliability thresholds.
- Confirm ethics/data-management expectations for model outputs, private mappings and notes.
- Review Pilot V4's and Pilot V5's frozen technical failures (both closed, immutable `FAIL`),
  and approve or revise the original-pair Pilot V6 plus replacement-fallback decision process;
  the software does not infer approval.
- Review the prospective generation-v4 method: no added target-facing style instruction, model-native
  reasoning, excluded reasoning traces, a 4096-token emergency envelope and technical
  response-length/reasoning telemetry. The calibration supports this engineering choice but
  does not itself constitute supervisor approval.

## Already fixed in the candidate protocol

- RQ2 prospectively compares MiniMax M3 with NVIDIA Nemotron 3 Super under the frozen
  configuration. Nemotron failed frozen generation-v2/v3 qualification; the intended pair must
  jointly pass generation-v4 Pilot V6. Replacement screening activates only if V6 fails.
- Two distinct seeded repetitions are retained.
- Length-limited text remains observed, is flagged, and receives sensitivity analysis.
- Human annotation is primary; automated classifier/judge work remains secondary.

No approval is inferred from this document or from passing software tests.
