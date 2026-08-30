# Supervisor meeting pack — Study V2 readiness

## Decision summary

The candidate main study now preserves the full 3×3 psychological design, two context
conditions and two repetitions while reducing technically unreliable endpoints. It plans
72 six-turn conversations and 432 response observations across the provisional original
MiniMax/Nemotron pair. No main-study data exist.

Pilot V1-V3 and the endpoint screen are immutable technical evidence. Pilot V3 established
MiniMax feasibility but produced eight HTTP 429 errors for Gemma/GLM. Nemotron's one-request
screen established connectivity and exact identity. Pilot V4 then completed under the
prespecified 512-token generation-v2 setting but failed because all 12 Nemotron responses
ended `finish_reason=length`. Pilot V5 later failed at generation-v3/1024. A content-free
methodology review and benign calibration prospectively introduced generation-v4: no added
target-facing style instruction, model-native reasoning, excluded reasoning traces and a
4096-token non-binding emergency envelope. Pilot V6 remains not run; replacement-screen v2 is
a fallback only if V6 fails.

## Requested supervisor decisions

- approve or revise the two-model pre-main-study deviation;
- approve or revise the draft human rubric and annotation procedure;
- confirm ethics/data-management expectations;
- review the frozen Pilot V4 failure, Pilot V5 qualification rule and main-study go/no-go decision.

## Demonstrable evidence

- configuration-derived balanced manifest;
- archived Pilot V4 audit plus offline-by-default Pilot V5 and main-study runners;
- strict free-endpoint qualification and exact-model checking;
- append-only resume and persistent HTTP-attempt accounting;
- protocol bundle and immutable evidence fingerprints;
- real-data-only annotation, audit and conversation-level analysis scaffolding.
