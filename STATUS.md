# Build Status

Last updated: 13 August 2026, 09:21 BST (Europe/London)

## Outcome

The Friday research prototype is implemented and validated locally. It now has
a cue-free, full-history six-turn runner; nine frozen scripts; a balanced
72-conversation manifest; immutable request/response provenance; blinded
seven-axis annotation; deterministic non-LLM NLP; conversation-level trajectory
analysis; a guarded grouped baseline; a disabled judge scaffold; deterministic
demo fixtures; a seven-view Streamlit dashboard; and the requested meeting pack.

No full study and no live OpenRouter call were run. The only generated responses
and annotations in the repository are explicitly labelled **DEMO FIXTURE - NOT
RESEARCH DATA**. The live path is a **TECHNICAL PILOT - DESCRIPTIVE ONLY** and
remains gated.

## Repository and source-material audit

- Active root: `C:\Users\Moham\OneDrive\Documents\project`.
- The Git repository has no commits and all project files are currently
  untracked. Existing research-method notes were preserved.
- The 31 July archive was inspected read-only at
  `C:\Users\Moham\Downloads\Mohamed_Ajab_MSc_Meeting_Pack_and_Prototype.zip`;
  it was not extracted over the active project.
- The revised proposal at
  `C:\Users\Moham\Downloads\MSc_Project_Proposal_and_Dissertation_Plan_Mohamed_Ajab_REVISED.docx`
  was reviewed for context. Its older 48-run/0-3 design was not allowed to
  override the supplied 72-run/seven-axis brief.
- `MSc_Dissertation_Bulletproof_Roadmap_12_Aug_2026.md` and the separate source
  file containing detailed seven-axis anchors were not found. The current
  `config/rubric.yaml` is therefore visibly marked as a conservative working
  draft pending supervisor/research-group confirmation.
- DOCX visual rendering was unavailable because LibreOffice/`soffice` is not
  installed. Text and tables were still inspected; no document was modified.

## Implemented milestones

### 1. Frozen configuration and manifest

- Three presentation levels, three safe themes, and nine parallel scripts.
- Exactly six user turns in every script.
- Three neutral, versioned theme prefixes shared across presentations.
- Exact condition names: `no_preloaded_context` and
  `standardised_preloaded_context`.
- Two exact configurable model slots plus versioned generation settings.
- Canonical SHA-256 configuration hashes.
- Deterministic seeded 72-row manifest and 29-field data dictionary.

### 2. Correct runner, provider, and evidence layer

- No target-facing system message or hidden benchmark/persona/rubric cue.
- Every request contains the exact optional prefix, all earlier user/assistant
  exchanges, and the current user turn.
- Dry-run builds all six auditable payloads without constructing a live client.
- The deterministic provider captures exact messages for tests and demos.
- OpenRouter uses exact slugs, catalogue preflight, non-streaming requests,
  typed errors, bounded retries, `Retry-After`, returned-model verification,
  usage/ID metadata, and credential redaction.
- The CLI pilot is fixed to one script x two models x two contexts x one
  repetition. Both generation calls and HTTP attempts (including retries) have
  a hard maximum of 24.
- Run headers and successful turn events are immutable. Each completed turn is
  written before the next call; resume never regenerates an existing success.

### 3. Human annotation and reliability

- Seven separate nullable 0-2 axes: A1, A2, A3, B1, B2, B3, C1.
- Primary A1/A2/A3 outcomes remain separate; there is no seven-axis total.
- Opaque keyed item IDs and separate internal mappings.
- Context shown only through the response being scored; explicit model,
  provider, context condition, and repetition metadata are absent.
- Append-only revisions, partial progress/resume, notes, uncertainty flag,
  re-rating aliases, tidy blinded export, exact agreement, and linear-weighted
  Cohen's kappa with honest unavailable states.

### 4. NLP, analysis, baseline, and judge boundary

- Offline word/sentence, pronoun, question, diversity, and versioned marker
  features.
- TF-IDF response/user similarity, turn drift, top terms, and guarded 2D SVD.
- Conversation-level A1/A2/A3 means/maxima, onset, persistence, recovery,
  final-versus-whole measures, completeness, matched comparisons, and seeded
  conversation/script-cluster bootstrap utilities.
- Explainable TF-IDF/logistic-regression baseline with conversation-grouped or
  leave-theme-out validation and refusal on inadequate data.
- Optional judge contract is marked `NOT VALIDATED - DISABLED BY DEFAULT`; it
  performs no call and cannot overwrite human annotations.

### 5. Dashboard, fixtures, and meeting exports

- Seven Streamlit views: Study Overview, Experiment Runner, Transcript &
  Provenance, Blinded Annotation, NLP Explorer, Trajectory Analysis, and
  Reproducibility & QA.
- Four deterministic demo conversations, 24 responses, 24 synthetic complete
  annotations, blinded items/map, and raw per-turn files generated through the
  production runner.
- Static offline meeting snapshot at `outputs/static_snapshot.html`.
- README, protocol, architecture, Friday pack, five-/two-minute demo scripts,
  supervisor decisions, restart checklist, and known limitations.
- Python 3.12 pin plus an exact 67-package tested environment snapshot.

## Final validation evidence

All commands used the project interpreter
`C:\Users\Moham\OneDrive\Documents\project\.venv\Scripts\python.exe`.

| Validation | Observed result |
|---|---|
| Python/environment imports | CPython 3.12.10, 64-bit; NumPy 2.5.1, Pandas 2.3.3, Plotly 6.9.0, Streamlit 1.60.0, scikit-learn 1.9.0 imported successfully |
| `python -m pip check` | No broken requirements; `requirements-lock.txt` exactly matched all 67 `pip freeze` lines |
| `python scripts\generate_manifest.py --validate` | 72 unique balanced runs; 72 factor cells, one row per cell |
| `python scripts\run_pilot.py` | Offline preflight only; 4 conversations, 24 maximum calls, no network generation |
| Disabled live check | `RUN_LIVE_PILOT=0 ... --live` exited 2 before provider construction |
| Demo regeneration | 4 conversations / 24 responses; 36 files remained byte-identical |
| Full Pytest | **73 passed in 32.15 seconds** |
| Ruff lint | `All checks passed!` |
| Ruff format check | 33 files already formatted |
| Compile check | `python -m compileall -q app.py src scripts tests` exited 0 |
| Streamlit AppTest | All seven views plus dry-run, fixture, provenance, annotation, NLP, trajectory, and disabled-live interactions passed within the full suite |
| Local visual smoke | Overview, Runner payload preview, and QA rendered at localhost; no browser console errors |
| Payload preview | Six offline requests visibly grew to 1/3/5/7/9/11 messages |
| Secret/ignore scan | 0 suspicious key files; `.env`, raw runs, and local annotations are ignored |
| Documentation links | 10 Markdown files checked; 0 broken local links |
| Required artifact check | 13/13 requested core artifacts present |

## Current evidence status

- **Demo fixture:** generated and usable offline; not research data.
- **Technical pilot:** implementation and preflight validated; not executed live.
- **Main study:** 72-run manifest generated; no conversation executed.
- **Human annotation:** workflow validated with synthetic annotations; no study
  ratings or reliability evidence yet.
- **Baseline/judge:** secondary scaffolds only; no validated automatic scorer.

## Remaining blockers and limitations

1. Recover or approve the authoritative detailed seven-axis anchors before any
   main annotation. Current anchors are an explicit draft, not clinically or
   psychometrically validated.
2. Recheck both exact OpenRouter slugs immediately before any live pilot.
   Free-model availability and provider infrastructure can change. Never accept
   substitution.
3. Obtain supervisor decisions on scripts, 72-versus-48 scope, exact endpoints,
   A3 threshold, annotator count/re-rating plan, ethics/provider terms, deadline,
   and word limit.
4. The repository has no baseline commit. Create a reviewed first commit or
   external snapshot before main data collection so rollback is possible.
5. The tracked demo deliberately uses fixed safe/risk-prone outputs. It proves
   pipeline behaviour only and cannot support conclusions about real models.
6. OneDrive can lock or conflict on files. Snapshot raw evidence outside the
   synced working tree before main collection.

## Next action

Use the offline five-minute path in `docs/DEMO_SCRIPT.md`, take the questions in
`docs/DECISIONS_FOR_SUPERVISOR.md` to Professor Cosma, and run the live technical
pilot only if it is approved and both exact endpoints pass same-day catalogue
preflight.
