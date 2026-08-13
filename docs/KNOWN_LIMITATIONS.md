# Known Limitations and Claim Boundaries

These limitations are part of the research design, not footnotes to remove after results are known.

## Evidence available now

- Deterministic fixture outputs demonstrate software behaviour only. They are **DEMO FIXTURE - NOT RESEARCH DATA**.
- A bounded four-conversation/24-call live path is a **TECHNICAL PILOT - DESCRIPTIVE ONLY**, even if it executes without error.
- The 72-row manifest is a reproducible plan, not an executed dataset.
- No comparative main-study result or successful live OpenRouter call should be inferred merely from the presence of provider code.

## Construct validity

The project operationalises selected textual behaviours—confirmation, enablement, safety intervention, epistemic instability, reality-boundary blurring, self-regulation undermining and appropriate challenge. These constructs may overlap, may omit relevant response qualities and may be interpreted differently by annotators.

The presentation conditions are synthetic prompting manipulations, not diagnoses or representations of all experiences associated with psychosis. A model score cannot be interpreted as a patient's mental state, clinical outcome or probability of harm.

The context prefix tests one narrowly standardised form of conversational continuity. It is not equivalent to long-term memory, personalisation, a real therapeutic relationship or a user's full interaction history.

## Rubric validity

The separate detailed rubric source requested in the project brief was unavailable locally. The current YAML contains conservative working definitions and anchors reconstructed from the supplied axis meanings. It is explicitly draft and not clinically or psychometrically validated.

Ordinal values 0, 1 and 2 do not establish equal intervals. No overall seven-axis total is valid: directions and conceptual roles differ. Even direction-consistent exploratory summaries would require prespecification and justification.

Exact agreement and weighted kappa quantify consistency, not construct correctness. Kappa can be undefined with sparse/constant ratings and sensitive to prevalence. One annotator's repeat scores are intra-rater evidence only, never inter-rater reliability.

## Scenario coverage and external validity

Nine scripts cover only three low-detail themes and one scripted progression. They cannot represent the diversity of language, cultural context, ambiguity, distress, conversational style or real-world chatbot use.

Fixed scripts strengthen control but reduce ecological validity. The user does not adapt to the model's answer. Safe exclusions—no violence, self-harm, graphic content or detailed illegal activity—are appropriate for this study but mean conclusions cannot extend to those settings.

Results would apply only to the exact endpoints, prompts, provider, collection dates and generation settings studied. They should not be generalised to a model family, vendor, future model update, all chatbots or all users.

## Endpoint and provider dependence

OpenRouter free endpoint availability, quotas, routing infrastructure and returned metadata can change. Exact slugs can disappear. The system refuses silent substitution, but this can cause missing cells or stop collection.

The provider may update weights/inference infrastructure behind an unchanged slug. A configured seed may be ignored or only partially supported. Recording a seed and payload improves auditability but does not guarantee identical remote output.

Latency and error rates reflect network/provider conditions as well as the endpoint. Provider moderation or transport blocks are missing/error observations, not generated refusals. Their distribution can create non-random missingness.

Two repetitions provide limited information about stochastic variability. Any decision to increase repetitions changes the manifest/protocol and resource requirements.

## Blinding limits

The annotation interface hides model, provider, context condition and repetition and uses opaque IDs. Nevertheless, writing style can allow an experienced rater to guess a model, and conversation content can reveal that some prior context exists. This is allocation concealment of explicit metadata, not guaranteed perceptual blinding.

The internal blinding map is necessary for analysis and must be access-controlled separately. Anyone who can inspect both it and public items can re-identify conditions.

Annotation notes can contain identifying guesses or sensitive commentary and require the same local access care as scores.

## Non-LLM NLP limits

Marker dictionaries are exact phrase lists. They are sensitive to paraphrase, casing/tokenisation choices, negation and context. For example, a phrase containing “confirm” can reject rather than endorse a claim; raw matching cannot reliably infer that distinction.

Density normalisation reduces response-length effects but does not remove them. TF-IDF similarities depend on the supplied corpus and do not measure semantic truth or clinical appropriateness. A two-dimensional SVD map discards information and its axes have no intrinsic clinical meaning.

Top terms can be unstable in small groups. NLP signals are exploratory aids for inspecting wording, not labels, safety scores or substitutes for the seven-axis human rubric.

## Trajectory and statistical limits

Six turns provide only a short trajectory. “Onset,” “persistence” and “recovery” are operational definitions within those six observations, not clinical processes.

Conversation-level summaries avoid turn-level pseudoreplication but reduce detail. Script-cluster bootstrap has only nine possible scripts in the full design and still relies on the scripts representing a meaningful sampling frame. Percentile intervals in small samples can be unstable.

Matched descriptive differences can be affected by missing pairs. Bootstrap intervals do not make the technical pilot powered or confirmatory. Multiple axes, trajectory measures and subgroup views create selective-reporting risk; primary outcomes and display order should be frozen in advance.

No causal clinical conclusion follows from a factorial prompt experiment on model outputs.

## Supervised baseline limits

The TF-IDF/logistic-regression baseline is a guarded scaffold, not a validated automatic annotator. Its default minimum of six conversations is a technical lower bound for forming grouped folds, not a claim that six conversations are scientifically sufficient.

Labels at multiple turns are correlated. Grouped folds prevent direct conversation leakage, and leave-one-theme-out is preferred where viable, but a small number of themes and scripts still limits generalisation. The current classifier treats ordinal scores as nominal classes and ignores ordering.

Macro-F1, balanced accuracy and confusion matrices can vary substantially with a small corpus. Interpretable coefficients describe association with the fitted training text, not causal linguistic features. Fixture/pilot fits must retain their non-evidence labels.

## Software and storage limits

This is a local research prototype, not a multi-user production service. It has no authentication, role-based permissions, database transaction service, remote backup, deployment hardening or formal audit certification.

Raw success files are exclusive and annotations are append-only, but a user with filesystem access can still edit or delete local files outside the application. Append-only therefore describes application behaviour, not tamper-proof storage.

OneDrive syncing can lock files or create sync conflicts. A raw-data backup/snapshot procedure is required before main collection and annotation.

The dashboard is a presentation layer, not the source of truth. Empty states and integration paths require final smoke testing after code changes. The latest actual validation outcome belongs in `STATUS.md`.

## Privacy, ethics and wellbeing limits

Synthetic prompts avoid personal/patient data, but provider outputs can unexpectedly contain distressing, stigmatising or identifying-looking invented content. Human annotation can expose researchers to repeated harmful language. A wellbeing and stopping/debrief procedure remains necessary.

Third-party processing still occurs during live calls even when text is synthetic. Provider terms, retention and university governance must be checked at collection time.

The prototype must not be offered to people seeking support and must not be represented as a treatment, crisis tool, diagnostic system, NHS integration or clinical risk screen.

## Novelty and literature claims

The software does not establish that this is the first benchmark of its kind. Novelty, prevalence and comparative claims require a current systematic literature search and accurate citations. Code functionality is not evidence for a scholarly novelty claim.

## Reporting rule

Every report, figure and presentation should state:

1. whether observations are fixture, technical pilot or main study;
2. exact endpoint/configuration and collection date for live data;
3. number of conversations and missing/error response slots;
4. rubric version and reliability evidence;
5. that prompts are synthetic and outcomes are non-clinical;
6. that conclusions are benchmark-specific and descriptive unless a justified analysis supports more.
