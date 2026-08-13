# Decisions for the Supervisor

This sheet separates academic/protocol decisions from software implementation. The safest default is listed so the project can remain paused without contaminating future evidence.

## Decisions needed before the technical pilot

| Decision | Current proposal | Safe default until decided | Record from meeting |
|---|---|---|---|
| May the bounded OpenRouter technical pilot run? | One fixed-belief script x two exact models x two contexts x one repetition; at most 24 calls | Do not run live; use fixture and zero-network dry-run | |
| Does a technical pilot require an ethics/governance check? | Synthetic prompts and model outputs only, but subject matter and third-party processing remain relevant | Confirm university process before live execution | |
| Are the two exact endpoint slugs acceptable? | Resolve `model_a` and `model_b` from environment; validate catalogue immediately before use; never substitute | Keep slots frozen but do not execute if either slug is unavailable | |
| Is the pilot script suitable? | One safe, non-graphic `fixed_belief` script used only for pipeline shakeout | Supervisor reviews wording before any live call | |
| Are provider terms/data handling acceptable? | Send only synthetic text; store local provenance; never send credentials as content | Review current OpenRouter terms and university guidance | |

## Decisions needed before rubric training/annotation

| Decision | Current proposal | Safe default until decided | Record from meeting |
|---|---|---|---|
| What is the authoritative detailed rubric source? | The supplied brief defines seven axes, but the separate detailed source file was unavailable | Treat `config/rubric.yaml` anchors as conservative draft only | |
| Are A1, A2 and A3 the three separate primary outcomes? | Yes; do not sum them | Keep separate and avoid a global total | |
| Is A3=2 the frozen “safety intervention” threshold? | Current configuration uses 2 | Report the raw A3 axis; do not foreground threshold events until approved | |
| Are B1/B2/B3/C1 exploratory? | Yes | Label exploratory in every table and plot | |
| May any exploratory summaries be formed? | Only direction-consistent, explicitly labelled summaries after prespecification | Keep every exploratory axis separate | |
| How many independent annotators? | Prefer at least two for a reliability subset if feasible | With one annotator, report only intra-rater re-rating reliability | |
| What re-rating fraction and delay? | Deterministic random sample under new blinded IDs; fraction/delay not yet frozen | Do not select the sample until fraction and timing are approved | |
| What training/adjudication process? | Codebook training, calibration set, notes/uncertainty flag, documented adjudication | Do not annotate main-study items until a training rule is written | |
| What annotator wellbeing procedure? | Planned stopping, break, debrief and escalation guidance | Limit any fixture exercise and agree procedure first | |

## Decisions needed before main-study execution

| Decision | Current proposal | Safe default until decided | Record from meeting |
|---|---|---|---|
| Working title | “A Controlled Multi-Turn Benchmark for Psychosis-Related Belief Reinforcement in Large Language Model Chatbots” | Retain as working, not a novelty or causal claim | |
| Aim | Build and validate a reproducible benchmark/pipeline for selected response trajectories in safe synthetic conversations | Keep non-clinical evaluation framing | |
| RQ1 | Distinguish targeted presentations from matched controls in primary harmful/protective outcomes | Retain pending confirmation | |
| RQ2 | Compare two exact endpoints under identical protocol | Retain, with endpoint/date/configuration-bounded claims | |
| RQ3 | Examine six-turn trajectories after repeated confirmation pressure | Retain, with conversation-level analysis | |
| RQ4 | Evaluate human-rubric reliability and any later grouped automated baseline | Keep automation secondary or remove from primary RQs | |
| Are presentation definitions acceptable? | `control`, `ambiguous`, `fixed_belief` as synthetic stimulus levels, never diagnoses | Do not use clinical group labels | |
| Are nine scripts sufficiently parallel? | Same themes and functional six-turn progression, with presentation-specific wording | Conduct supervisor/content review before freezing v1 | |
| Are prefixes balanced and neutral? | One shared prefix per theme; no desired-response cue | Review and freeze alongside scripts | |
| Is two repetitions sufficient/appropriate? | Two per factorial cell, yielding 72 conversations | Treat as a feasibility design until justified; revise manifest version if changed | |
| How should endpoint availability changes be handled? | Recheck immediately before execution; abort rather than substitute | Never mix substitute endpoints into the same study version | |
| What constitutes a protocol deviation? | Any change to script, prefix, model slug, generation settings, rubric or execution status | Version, hash and report every deviation | |

## Analysis decisions

| Decision | Current proposal | Safe default until decided | Record from meeting |
|---|---|---|---|
| Primary estimands | A1/A2/A3 means and specified trajectory events at conversation level | Present raw distributions and missingness alongside summaries | |
| Persistence definition | Proportion/pattern of post-onset A1=2 after first A1=2 | Treat as descriptive until operational definition is signed off | |
| Recovery definition | Later A1 below 2 after a high-A1 turn | Treat as descriptive until approved | |
| Comparison matching | Script, repetition and the non-compared factor | Do not compare unmatched rows as paired |
| Bootstrap unit | Complete conversation or complete script cluster; matched comparisons resample complete pairs/clusters | Never resample individual turns | |
| Confidence intervals/significance | Seeded percentile intervals can describe uncertainty | Do not present pilot p-values or unstable significance claims | |
| Missing provider responses | Typed missing/error observations | Never impute them as safe refusals | |
| Multiple outcomes | Primary A1/A2/A3 and several exploratory measures | Prespecify reporting order and avoid selective highlighting | |
| NLP role | Explainable exploratory signals from saved text | Never treat lexical density as a clinical or rubric label | |
| Baseline role | Secondary TF-IDF/logistic scaffold after enough labels | Do not treat fixture/pilot training as dissertation evidence | |

## Suggested meeting decisions in priority order

1. Confirm the non-clinical scope, aim and research questions.
2. Decide whether the detailed rubric source can be provided; approve or replace the conservative working anchors.
3. Review the presentation definitions, nine scripts and three prefixes for construct validity, safety and parallelism.
4. Agree primary outcomes, trajectory rules, missingness handling and whether any exploratory summaries are permitted.
5. Agree annotator count, training, re-rating sample, reliability terminology and adjudication/wellbeing procedure.
6. Decide whether the maximum-24-call technical pilot is authorised and what checks precede it.
7. Freeze endpoint-selection and model-unavailability rules.
8. Decide whether the baseline belongs in RQ4, future work or implementation-only validation.

## Decision log template

Copy one block per decision into the project log:

```text
Decision ID:
Date/time (UK):
People present:
Question:
Decision:
Rationale:
Files/versions affected:
Required action and owner:
Deadline:
```

If a decision changes a frozen configuration, increment the relevant version, regenerate the manifest/hash and keep earlier evidence under its original version. Do not edit raw records to make them match a later decision.
