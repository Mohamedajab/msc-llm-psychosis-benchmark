# Supervisor meeting pack — Study V2 readiness

## Decision summary

The candidate main study now preserves the full 3×3 psychological design, two context
conditions and two repetitions while reducing technically unreliable endpoints. It plans
72 six-turn conversations and 432 response observations across MiniMax M3 and Nemotron
Super. No main-study data exist.

Pilot V1-V3 and the endpoint screen are immutable technical evidence. Pilot V3 established
MiniMax feasibility but produced eight HTTP 429 errors for Gemma/GLM. Nemotron's one-request
screen established connectivity and exact identity, but `finish_reason=length` at 350 tokens
requires Pilot V4 qualification under the prespecified 512-token generation-v2 setting.

## Requested supervisor decisions

- approve or revise the two-model pre-main-study deviation;
- approve or revise the draft human rubric and annotation procedure;
- confirm ethics/data-management expectations;
- agree the Pilot V4 qualification threshold and main-study go/no-go decision.

## Demonstrable evidence

- configuration-derived balanced manifest;
- offline-by-default Pilot V4 and main-study runners;
- strict free-endpoint qualification and exact-model checking;
- append-only resume and persistent HTTP-attempt accounting;
- protocol bundle and immutable evidence fingerprints;
- real-data-only annotation, audit and conversation-level analysis scaffolding.
