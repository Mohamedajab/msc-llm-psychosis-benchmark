# Final Study Provenance

This document records the evidence path for the completed and frozen Study V2.1 artefact. The
verification work described here reads existing evidence only; it does not change the study.

## Evidence flow

```text
Frozen configuration and scenarios
        |
        v
72-row experiment manifest
        |
        v
Target-model requests
        |
        v
Append-only response and error evidence
        |
        v
Blinded annotation items
        |
        +-------------------------+
        |                         |
        v                         v
Primary human annotation    Three supplementary LLM judges
        |                         |
        +------------+------------+
                     v
             Frozen analysis outputs
                     |
                     v
           Dashboard and dissertation reporting
```

## Repository evidence

| Stage | Repository evidence |
|---|---|
| Frozen study definition | `protocol/study-v2.1.0/`, `config/final/study-v2.1.0/models.yaml`, `config/scenarios/`, `config/histories/`, `config/rubric.yaml` |
| Experiment manifest | `outputs/study-v2.1.0/experiment_manifest.csv` |
| Request construction | `src/payloads.py`, `src/conversation_runner.py`, `src/study_execution.py` |
| Raw study evidence | `data/raw/study-v2/` |
| Blinding and annotation preparation | `src/annotation.py`, `scripts/prepare_main_study_annotations.py` |
| Primary human ratings | `data/annotations/annotations.jsonl` (`annotator_1`, initial round) |
| Supplementary judge ratings | `data/private/judges/<judge-id>/successes/` |
| Descriptive and agreement outputs | `data/private/analysis-v1/` |
| Primary research-question outputs | `data/private/analysis-v2/` |
| Final exploratory outputs | `data/private/analysis-v3/` |
| Analysis freeze record | `data/private/analysis-freeze-v1.sha256.txt` |
| Dashboard | `app.py` |

## Integrity and recovery

Each successful target-model turn is written to its own immutable record. Failed technical
attempts are stored separately and remain available for audit. After a temporary failure, the
runner reconstructs the conversation from saved successes and continues from the first genuinely
missing response. It does not regenerate an already accepted successful turn.

Annotation items are blinded before scoring. The primary evidence is the completed human
annotation by one primary annotator; no human inter-rater reliability claim is made. The three LLM
judges are separate, blinded supplementary evidence and do not overwrite the human ratings.

The final analysis was produced by the frozen scripts:

- `scripts/analyse_completed_study.py`
- `scripts/analyse_research_questions.py`
- `scripts/analyse_final_exploratory.py`

Their saved outputs and recorded SHA-256 values are checked by
`scripts/verify_final_release.py`. This verification does not rerun collection, judging or the
statistical analysis.
