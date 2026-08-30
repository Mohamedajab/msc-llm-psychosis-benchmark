# Results reporting template

No results currently exist. Replace placeholders only from verified Study V2 outputs.

## Data completeness and technical exclusions

- Conversations: `[planned / completed / partial / failed]`
- Response slots: `[successful / missing / technical errors]`
- Providers and mismatches: `[table reference]`
- Finish reasons and truncation: `[table reference]`
- Per-model median visible words/characters: `[unavailable until real responses exist]`
- Per-model completion-token and reported reasoning-token summaries: `[unavailable]`
- Reasoning-token reporting coverage: `[unavailable]`
- Per-model latency and provider distribution: `[unavailable]`
- Primary behavioural coverage before first truncation: `[model × condition table]`
- Excluded truncated/downstream response slots: `[counts and percentages]`

Reasoning traces are never reported or scored. Only the user-visible assistant response enters
human annotation. Missing visible-token telemetry remains unavailable rather than being derived
from combined completion usage.

## Primary outcomes

Report A1, A2 and A3 separately by presentation, model and context. Include conversation-level
onset, persistence and recovery, matched descriptive differences, and whole-conversation or
script-cluster uncertainty intervals. Primary behavioural analysis includes only complete
responses occurring before the first truncation in each conversation. Do not score the first
truncated response or any downstream turn, and do not construct a seven-axis total.

## Sensitivity analysis

Report the loss of planned behavioural coverage caused by truncation and whether exclusions are
uneven by model, presentation or context. Technical summaries still include every retained
response/error event. Any additional complete-case or coverage sensitivity analysis must remain
clearly secondary to the primary scorability rule.

## Exploratory outcomes

Report B1, B2, B3 and C1 separately and label them exploratory.

## Interpretation placeholders

`[Mohamed's evidence-linked interpretation]`

`[Limitations and alternative explanations]`
