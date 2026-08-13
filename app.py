# ruff: noqa: E501
"""Professional local dashboard for the controlled six-turn benchmark.

Normal import and Streamlit startup are deliberately offline.  The only code path
that constructs an OpenRouter client or checks its catalogue is the explicitly
confirmed live technical-pilot button handler.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from src.annotation import (
    AnnotationError,
    AnnotationPersistenceError,
    AnnotationStore,
    build_blinded_items,
    rubric_display_rows,
    tidy_annotation_frame,
)
from src.config_loader import (
    ConfigurationError,
    canonical_hash,
    configuration_bundle_hash,
    generation_for_repetition,
    load_histories,
    load_models,
    load_rubric,
    load_scripts,
    resolve_model_ids,
    validate_catalogue,
)
from src.conversation_runner import ConversationRunner, create_run_header
from src.manifest import STUDY_VERSION, generate_manifest, manifest_dataframe, validate_manifest
from src.nlp_features import (
    conversation_records_to_frame,
    extract_response_features,
    project_responses_2d,
    top_tfidf_terms,
)
from src.provider_client import DeterministicFixtureProvider, OpenRouterProvider
from src.schemas import (
    AnnotationEvent,
    AxisScores,
    ContextCondition,
    ConversationRecord,
    HistoryPrefix,
    ModelsConfig,
    RubricConfig,
    RunHeader,
    ScriptConfig,
)
from src.storage import RawRunStore, safe_filename
from src.trajectory_analysis import (
    matched_descriptive_comparisons,
    summarize_conversations,
)

BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = Path(os.getenv("BENCHMARK_DATA_DIR", str(BASE_DIR / "data")))
RAW_RUN_DIR = DATA_DIR / "raw" / "runs"
ANNOTATION_LOG = DATA_DIR / "annotations" / "annotations.jsonl"

VIEWS: tuple[str, ...] = (
    "Study Overview",
    "Experiment Runner",
    "Transcript & Provenance",
    "Blinded Annotation",
    "NLP Explorer",
    "Trajectory Analysis",
    "Reproducibility & QA",
)

EXECUTION_MODES: tuple[str, ...] = (
    "Dry run (offline payload preview)",
    "Deterministic fixture (offline execution)",
    "OpenRouter (live technical pilot)",
)


@dataclass(frozen=True)
class LocalConfiguration:
    scripts: tuple[ScriptConfig, ...]
    histories: tuple[HistoryPrefix, ...]
    models: ModelsConfig
    rubric: RubricConfig
    bundle_hash: str


@st.cache_data(show_spinner=False)
def load_local_configuration() -> LocalConfiguration:
    """Load and validate local files only; this function never uses the network."""
    scripts = tuple(load_scripts(CONFIG_DIR / "scenarios"))
    histories = tuple(load_histories(CONFIG_DIR / "histories"))
    models = load_models(CONFIG_DIR / "models.yaml")
    rubric = load_rubric(CONFIG_DIR / "rubric.yaml")
    errors = validate_catalogue(list(scripts), list(histories))
    if errors:
        raise ConfigurationError("; ".join(errors))
    return LocalConfiguration(
        scripts=scripts,
        histories=histories,
        models=models,
        rubric=rubric,
        bundle_hash=configuration_bundle_hash(list(scripts), list(histories), models),
    )


def initialise_state() -> None:
    st.session_state.setdefault("current_run_id", None)
    st.session_state.setdefault("dry_run_payloads", [])
    st.session_state.setdefault("dry_run_label", "")


def raw_store() -> RawRunStore:
    return RawRunStore(RAW_RUN_DIR)


def load_available_records(
    store: RawRunStore | None = None,
) -> tuple[list[ConversationRecord], list[str]]:
    """Load every readable raw record while isolating malformed-run errors."""
    store = store or raw_store()
    records: list[ConversationRecord] = []
    errors: list[str] = []
    try:
        run_ids = store.list_run_ids()
    except (OSError, ValueError) as error:
        return [], [f"Raw run directory could not be read: {error}"]
    for run_id in run_ids:
        try:
            records.append(store.load(run_id))
        except (OSError, ValueError) as error:
            errors.append(f"{run_id}: {error}")
    records.sort(key=lambda record: record.header.created_at, reverse=True)
    return records, errors


def records_by_run_id(records: Iterable[ConversationRecord]) -> dict[str, ConversationRecord]:
    return {record.header.run_id: record for record in records}


def history_for_script(script: ScriptConfig, histories: Sequence[HistoryPrefix]) -> HistoryPrefix:
    try:
        return next(history for history in histories if history.history_id == script.history_id)
    except StopIteration as error:
        raise ConfigurationError(
            f"No frozen prefix was found for script {script.script_id}"
        ) from error


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _record_matches_header(existing: RunHeader, intended: RunHeader) -> bool:
    """Compare immutable design fields while allowing the original creation time."""
    fields = (
        "study_version",
        "run_id",
        "data_status",
        "script_id",
        "script_version",
        "theme",
        "presentation_level",
        "context_condition",
        "history_id",
        "model_slot",
        "requested_model_id",
        "provider",
        "repetition",
        "generation_config",
        "configuration_version",
        "configuration_hash",
    )
    return all(getattr(existing, field) == getattr(intended, field) for field in fields)


def create_or_resume_header(
    *,
    store: RawRunStore,
    run_id: str,
    data_status: str,
    script: ScriptConfig,
    condition: ContextCondition,
    model_slot: str,
    model_id: str,
    configuration: LocalConfiguration,
) -> RunHeader:
    """Create an intended header or reuse exactly matching immutable metadata."""
    intended = create_run_header(
        study_version=STUDY_VERSION,
        run_id=run_id,
        data_status=data_status,  # type: ignore[arg-type]
        script=script,
        condition=condition,
        model_slot=model_slot,
        model_id=model_id,
        repetition=1,
        generation=generation_for_repetition(configuration.models, 1),
        configuration_version=configuration.models.version,
        configuration_hash=configuration.bundle_hash,
    )
    header_path = store.run_directory(run_id) / "run.json"
    if not header_path.exists():
        return intended
    existing = store.load(run_id).header
    if not _record_matches_header(existing, intended):
        raise FileExistsError(
            "That run identifier already belongs to different immutable settings. "
            "Choose a new run identifier."
        )
    return existing


def validate_run_identifier(value: str) -> str:
    run_id = value.strip()
    if not run_id:
        raise ValueError("Enter a run identifier.")
    if safe_filename(run_id) != run_id:
        raise ValueError(
            "Use only letters, numbers, full stops, underscores, and hyphens in the run identifier."
        )
    return run_id


def status_banner(records: Sequence[ConversationRecord] | None = None) -> None:
    """Keep evidence status prominent and impossible to confuse with findings."""
    statuses = {record.header.data_status for record in (records or [])}
    if not records or "demo_fixture" in statuses:
        st.warning(
            "DEMO FIXTURE - NOT RESEARCH DATA. Offline fixture responses demonstrate the workflow only."
        )
    if not records or "technical_pilot" in statuses:
        st.info(
            "TECHNICAL PILOT - DESCRIPTIVE ONLY. Live pilot output is an engineering check, not dissertation evidence."
        )


def render_global_header(view: str) -> None:
    st.title("Controlled Multi-Turn LLM Safety Benchmark")
    st.caption(f"{view} · MSc Advanced Computer Science research prototype · synthetic inputs only")
    status_banner()
    st.caption(
        "Not a diagnostic, therapeutic, clinical, or patient-facing system. No real patient data are used."
    )


def render_overview(configuration: LocalConfiguration) -> None:
    st.header("Study Overview")
    st.write(
        "This prototype evaluates how two fixed language-model slots respond across six controlled turns when synthetic users express increasingly certain unsupported interpretations. The contribution is the controlled, auditable research pipeline—not an automated clinical judgement."
    )

    metric_columns = st.columns(4)
    metric_columns[0].metric("Planned conversations", "72")
    metric_columns[1].metric("Frozen scripts", len(configuration.scripts))
    metric_columns[2].metric("Turns per conversation", "6")
    metric_columns[3].metric("Planned responses", "432")

    st.subheader("Research questions")
    questions = (
        "RQ1 — How does presentation level affect belief-confirming and harm-enabling responses across a six-turn exchange?",
        "RQ2 — How do the two fixed target-model slots differ on the primary A1, A2, and A3 outcomes?",
        "RQ3 — Does standardised preloaded context change response trajectories compared with no preloaded context?",
        "RQ4 — At what turn do high-risk confirmation or protective safety intervention first appear, persist, or recover?",
    )
    for question in questions:
        st.markdown(f"- {question}")

    design = pd.DataFrame(
        [
            ("Presentation level", "3", "control, ambiguous, fixed-belief"),
            ("Scenario theme", "3", "monitoring, personal messages, AI relationship"),
            ("Target model slot", "2", "two exact configured model identifiers"),
            ("Context condition", "2", "none or one frozen standardised prefix"),
            ("Repetition", "2", "two planned repetitions"),
            ("Conversation length", "6 turns", "fixed for every script"),
        ],
        columns=["Factor", "Levels", "Protocol"],
    )
    st.subheader("Frozen factorial design")
    st.dataframe(design, hide_index=True, width="stretch")

    st.subheader("Evidence-status boundaries")
    status_table = pd.DataFrame(
        [
            (
                "Planned study",
                "72 manifest rows",
                "Design coverage only; no claim that collection is complete",
            ),
            (
                "Technical pilot",
                "Maximum four conversations / 24 calls in the documented pilot",
                "Engineering and feasibility evidence; descriptive only",
            ),
            (
                "Demo fixture",
                "Deterministic offline responses",
                "Interface and workflow demonstration; never research data",
            ),
        ],
        columns=["Status", "Scope", "Permitted interpretation"],
    )
    st.dataframe(status_table, hide_index=True, width="stretch")


def _selection_controls(
    configuration: LocalConfiguration,
) -> tuple[ScriptConfig, ContextCondition, str, str, str]:
    script_lookup = {script.script_id: script for script in configuration.scripts}
    script_id = st.selectbox(
        "Frozen six-turn script",
        options=sorted(script_lookup),
        format_func=lambda value: script_lookup[value].title,
    )
    condition = st.selectbox(
        "Context condition",
        options=list(ContextCondition),
        format_func=lambda value: value.value.replace("_", " "),
    )
    mode = st.selectbox("Execution mode", options=EXECUTION_MODES)
    model_slot = ""
    fixture_profile = "safe"
    if mode == EXECUTION_MODES[1]:
        fixture_profile = st.selectbox(
            "Fixture response profile",
            options=("safe", "risk_prone"),
            format_func=lambda value: value.replace("_", " ").title(),
        )
    else:
        model_slot = st.selectbox(
            "Target model slot",
            options=("model_a", "model_b"),
            format_func=lambda value: value.replace("_", " ").title(),
        )
    return script_lookup[script_id], condition, mode, model_slot, fixture_profile


def _render_script_preview(script: ScriptConfig, prefix: HistoryPrefix) -> None:
    with st.expander("Review frozen inputs", expanded=False):
        st.caption(
            "These are the exact scripted user messages. Experimental condition labels and rubric instructions are never inserted into target requests."
        )
        for turn_number, message in enumerate(script.turns, start=1):
            st.markdown(f"**Turn {turn_number}**")
            st.write(message)
        st.markdown("**Standardised prefix available for this theme**")
        st.caption(
            f"{len(prefix.messages)} messages; included only in the standardised-preloaded-context condition."
        )


def _render_dry_payloads(payloads: Sequence[dict[str, Any]]) -> None:
    if not payloads:
        return
    st.subheader("Exact six-request dry-run preview")
    st.caption(
        "No provider was called. Later requests contain explicit assistant placeholders because live response text does not exist yet; message order, parameters, model ID, and payload hashes are exact."
    )
    for payload in payloads:
        messages = payload["messages"]
        with st.expander(
            f"Request {payload['turn_number']} · {len(messages)} ordered messages",
            expanded=payload["turn_number"] == 1,
        ):
            st.dataframe(pd.DataFrame(messages), hide_index=True, width="stretch")
            st.json(payload)
    st.download_button(
        "Download dry-run payload JSON",
        data=json.dumps(payloads, indent=2, ensure_ascii=False),
        file_name="six_turn_dry_run_payloads.json",
        mime="application/json",
    )


def _render_run_result(record: ConversationRecord) -> None:
    if record.header.data_status == "demo_fixture":
        st.warning("DEMO FIXTURE - NOT RESEARCH DATA")
    else:
        st.info("TECHNICAL PILOT - DESCRIPTIVE ONLY")
    if record.status.value == "completed":
        st.success(f"Run {record.header.run_id} completed all six turns.")
    elif record.errors:
        st.error(
            f"Run stopped after {len(record.turns)} successful turn(s). The technical error is stored separately from model responses."
        )
    else:
        st.info(f"Run status: {record.status.value}")
    st.dataframe(
        pd.DataFrame(
            {
                "Turn": [turn.turn_number for turn in record.turns],
                "Observation": [turn.result.status.value for turn in record.turns],
                "Request messages": [len(turn.request_messages) for turn in record.turns],
                "Latency (ms)": [round(turn.result.latency_ms, 2) for turn in record.turns],
            }
        ),
        hide_index=True,
        width="stretch",
    )


def render_runner(configuration: LocalConfiguration) -> None:
    st.header("Experiment Runner")
    st.write(
        "Every execution uses exactly six frozen user turns and retains the complete earlier dialogue. Dry-run and fixture modes are fully offline."
    )
    st.metric("Fixed conversation length", "6 turns")

    left, right = st.columns([3, 2])
    with left:
        script, condition, mode, model_slot, fixture_profile = _selection_controls(configuration)
        run_id_input = st.text_input(
            "Run identifier",
            value="friday-demo-run",
            help="Existing matching runs resume safely; successful turns are never overwritten.",
        )
    prefix = history_for_script(script, configuration.histories)
    with right:
        st.markdown("**Selected protocol cell**")
        st.write(f"Theme: {script.theme.value.replace('_', ' ')}")
        st.write(f"Presentation: {script.presentation_level.value.replace('_', ' ')}")
        st.write(f"Context: {condition.value.replace('_', ' ')}")
        st.write("Turns: 6 (fixed)")
        st.write(f"Generation config: {configuration.models.generation.version}")
    _render_script_preview(script, prefix)

    try:
        resolved_models = resolve_model_ids(configuration.models)
    except ConfigurationError as error:
        st.error(f"Exact target model configuration is invalid: {error}")
        return
    store = raw_store()

    if mode == EXECUTION_MODES[0]:
        st.info("OFFLINE DRY RUN — exact request construction only; zero network calls")
        if st.button("Preview exact six payloads", type="primary"):
            try:
                run_id = validate_run_identifier(run_id_input)
                header = create_run_header(
                    study_version=STUDY_VERSION,
                    run_id=run_id,
                    data_status="planned_study",
                    script=script,
                    condition=condition,
                    model_slot=model_slot,
                    model_id=resolved_models[model_slot],
                    repetition=1,
                    generation=generation_for_repetition(configuration.models, 1),
                    configuration_version=configuration.models.version,
                    configuration_hash=configuration.bundle_hash,
                )
                runner = ConversationRunner(DeterministicFixtureProvider(), store)
                payloads = runner.dry_run(header=header, script=script, prefix=prefix)
            except (ConfigurationError, ValueError) as error:
                st.error(str(error))
            else:
                st.session_state.dry_run_payloads = payloads
                st.session_state.dry_run_label = run_id
                st.success(
                    "Six payloads constructed locally. network_called is false for every request."
                )
        _render_dry_payloads(st.session_state.dry_run_payloads)

    elif mode == EXECUTION_MODES[1]:
        st.warning("DEMO FIXTURE - NOT RESEARCH DATA")
        st.caption(
            "The deterministic provider exists for reproducible demonstrations and tests. It is not a target-model evaluation."
        )
        if st.button("Run or resume six-turn fixture", type="primary"):
            try:
                run_id = validate_run_identifier(run_id_input)
                model_id = f"fixture/{fixture_profile}-v1"
                header = create_or_resume_header(
                    store=store,
                    run_id=run_id,
                    data_status="demo_fixture",
                    script=script,
                    condition=condition,
                    model_slot=f"fixture_{fixture_profile}",
                    model_id=model_id,
                    configuration=configuration,
                )
                provider = DeterministicFixtureProvider(profile=fixture_profile)
                with st.spinner("Running six deterministic offline turns…"):
                    record = ConversationRunner(provider, store).run_or_resume(
                        header=header, script=script, prefix=prefix
                    )
            except (ConfigurationError, FileExistsError, OSError, ValueError) as error:
                st.error(str(error))
            else:
                st.session_state.current_run_id = record.header.run_id
                _render_run_result(record)

    else:
        st.info("TECHNICAL PILOT - DESCRIPTIVE ONLY")
        model_id = resolved_models[model_slot]
        st.code(model_id, language=None)
        key_present = bool(os.getenv("OPENROUTER_API_KEY", "").strip())
        if not key_present:
            st.warning(
                "OPENROUTER_API_KEY is not present in this process. Live execution remains disabled; dry-run and fixture modes still work."
            )
        live_confirmation = st.checkbox(
            "I confirm that this will contact OpenRouter, use the exact model shown above, and create a technical-pilot record."
        )
        live_button = st.button(
            "Run or resume live technical pilot",
            type="primary",
            disabled=not (key_present and live_confirmation),
        )
        st.caption(
            "No catalogue check or generation request occurs until the enabled button is clicked. The API key is never displayed or stored."
        )
        if live_button:
            try:
                run_id = validate_run_identifier(run_id_input)
                provider = OpenRouterProvider()
                with st.spinner("Checking the exact model slug in the live catalogue…"):
                    provider.validate_exact_model(
                        model_id,
                        timeout_seconds=configuration.models.generation.timeout_seconds,
                    )
                header = create_or_resume_header(
                    store=store,
                    run_id=run_id,
                    data_status="technical_pilot",
                    script=script,
                    condition=condition,
                    model_slot=model_slot,
                    model_id=model_id,
                    configuration=configuration,
                )
                with st.spinner("Running or resuming the six-turn technical pilot…"):
                    record = ConversationRunner(provider, store).run_or_resume(
                        header=header, script=script, prefix=prefix
                    )
            except (FileExistsError, OSError, RuntimeError, ValueError) as error:
                st.error(str(error))
            else:
                st.session_state.current_run_id = record.header.run_id
                _render_run_result(record)


def _metadata_frame(record: ConversationRecord) -> pd.DataFrame:
    header = record.header
    rows = [
        ("Run ID", header.run_id),
        ("Evidence status", header.data_status),
        ("Run status", record.status.value),
        ("Script ID / version", f"{header.script_id} / {header.script_version}"),
        ("Theme", header.theme.value),
        ("Presentation level", header.presentation_level.value),
        ("Context condition", header.context_condition.value),
        ("History ID", header.history_id or "not included"),
        ("Model slot", header.model_slot),
        ("Requested exact model", header.requested_model_id),
        ("Provider", header.provider),
        ("Created UTC", header.created_at.isoformat()),
        ("Configuration version", header.configuration_version),
        ("Configuration SHA-256", header.configuration_hash),
    ]
    return pd.DataFrame(rows, columns=["Field", "Value"])


def render_provenance() -> None:
    st.header("Transcript & Provenance")
    records, load_errors = load_available_records()
    if load_errors:
        st.error("Some raw records could not be loaded.")
        with st.expander("Raw-record load errors"):
            st.code("\n".join(load_errors))
    if not records:
        st.info(
            "No raw conversations are available. Run a deterministic fixture or an explicitly confirmed technical pilot first."
        )
        return

    status_banner(records)
    lookup = records_by_run_id(records)
    run_ids = list(lookup)
    preferred = st.session_state.current_run_id
    initial = run_ids.index(preferred) if preferred in run_ids else 0
    selected_id = st.selectbox("Saved run", options=run_ids, index=initial)
    record = lookup[selected_id]
    st.dataframe(_metadata_frame(record), hide_index=True, width="stretch")

    st.subheader("Exact request-message growth")
    growth = pd.DataFrame(
        [
            {
                "turn_number": turn.turn_number,
                "message_count": len(turn.request_messages),
                "roles": " → ".join(message.role for message in turn.request_messages),
                "payload_sha256": turn.request_payload_hash,
            }
            for turn in record.turns
        ]
    )
    if growth.empty:
        st.info("This run has no successful response turns yet.")
    else:
        st.dataframe(growth, hide_index=True, width="stretch")

    for turn in record.turns:
        with st.expander(
            f"Turn {turn.turn_number}: exact request, response, and provider metadata",
            expanded=turn.turn_number == 1,
        ):
            st.markdown("**Exact ordered request messages**")
            st.dataframe(
                pd.DataFrame([message.model_dump() for message in turn.request_messages]),
                hide_index=True,
                width="stretch",
            )
            st.markdown("**Assistant response**")
            st.write(turn.result.text)
            provider_metadata = {
                "request_payload_hash": turn.request_payload_hash,
                "request_parameters": turn.request_parameters,
                "request_timestamp": turn.request_timestamp.isoformat(),
                "response_timestamp": turn.response_timestamp.isoformat(),
                "status": turn.result.status.value,
                "requested_model_id": turn.result.requested_model_id,
                "resolved_model_id": turn.result.resolved_model_id,
                "provider_name": turn.result.provider_name,
                "generation_id": turn.result.generation_id,
                "request_id": turn.result.request_id,
                "finish_reason": turn.result.finish_reason,
                "usage": (turn.result.usage.model_dump() if turn.result.usage else None),
                "latency_ms": turn.result.latency_ms,
                "retry_count": turn.result.retry_count,
                "http_status": turn.result.http_status,
            }
            st.json(provider_metadata)

    st.subheader("Technical error observations")
    if not record.errors:
        st.success("No separate transport/provider error observations are stored for this run.")
    else:
        for error in record.errors:
            st.error(
                f"Turn {error.turn_number}: {error.result.status.value} · {error.result.error_type or 'unspecified error'}"
            )
            st.json(error.model_dump(mode="json"))

    st.download_button(
        "Download complete run JSON",
        data=record.model_dump_json(indent=2),
        file_name=f"{record.header.run_id}.json",
        mime="application/json",
    )


def _blinding_material(
    configuration: LocalConfiguration, records: Sequence[ConversationRecord]
) -> tuple[list[Any], list[Any]]:
    # A deployment can provide a private stable key. The local fallback stays out of
    # annotator-facing records and is sufficient only for this single-user prototype.
    key = os.getenv("ANNOTATION_BLINDING_KEY") or ("local-prototype-" + configuration.bundle_hash)
    return build_blinded_items(records, blinding_key=key)


def _score_index(value: int | None) -> int:
    return 0 if value is None else value + 1


def render_annotation(configuration: LocalConfiguration) -> None:
    st.header("Blinded Annotation")
    st.write(
        "This workspace exposes only opaque item identifiers, the conversation available at the scored turn, the response, and the draft rubric. Model, provider, context condition, and repetition are not shown."
    )
    records, load_errors = load_available_records()
    if load_errors:
        st.warning("Some unavailable raw records were excluded from item preparation.")
    if not records:
        st.info(
            "No responses are available for annotation. Create an offline fixture run first, then return here."
        )
        return

    try:
        items, _internal_mapping = _blinding_material(configuration, records)
    except AnnotationError as error:
        st.error(f"Blinded items could not be prepared: {error}")
        return
    if not items:
        st.info("No successful assistant responses are available to score.")
        return

    store = AnnotationStore(ANNOTATION_LOG)
    annotator_id = st.text_input(
        "Pseudonymous annotator ID",
        value="annotator_01",
        help="Use a stable pseudonym; do not enter a name or email address.",
    ).strip()
    try:
        latest_events = store.latest_events(annotator_id=annotator_id)
    except AnnotationPersistenceError as error:
        st.error(str(error))
        return
    latest_by_item = {event.blinded_item_id: event for event in latest_events}
    complete_count = sum(event.scores.complete() for event in latest_events)
    progress_columns = st.columns(3)
    progress_columns[0].metric("Blinded items", len(items))
    progress_columns[1].metric("Complete", complete_count)
    progress_columns[2].metric("Remaining", max(0, len(items) - complete_count))

    incomplete_ids = {
        item.blinded_item_id for item in store.incomplete_items(items, annotator_id=annotator_id)
    }
    item_lookup = {item.blinded_item_id: item for item in items}
    item_id = st.selectbox(
        "Blinded item",
        options=list(item_lookup),
        format_func=lambda value: (
            f"{value} · {'incomplete' if value in incomplete_ids else 'complete'}"
        ),
    )
    item = item_lookup[item_id]
    latest = latest_by_item.get(item_id)

    st.caption(
        f"Blinded item ID: {item.blinded_item_id} · Rating round: {item.rating_round} · Turn number: {item.turn_number}"
    )
    st.subheader("Conversation available at this turn")
    for message in item.conversation_context:
        with st.container(border=True):
            st.caption(message.role.upper())
            st.write(message.content)
    with st.container(border=True):
        st.caption("ASSISTANT RESPONSE TO SCORE")
        st.write(item.response_to_score)

    rubric_rows = rubric_display_rows(configuration.rubric)
    saved_scores = latest.scores.model_dump() if latest else {}
    score_options: list[int | None] = [None, 0, 1, 2]
    st.caption(
        "Draft research rubric; not clinically validated. Every axis is nullable: choose Not rated to save partial progress. No combined seven-axis total is calculated."
    )
    with st.form(f"annotation::{annotator_id}::{item.blinded_item_id}"):
        scores: dict[str, int | None] = {}
        for axis in rubric_rows:
            st.markdown(
                f"**{axis['axis_id']} — {axis['name']}** · {axis['role']} · higher is {axis['direction']}"
            )
            st.caption(axis["definition"])
            current = saved_scores.get(axis["axis_id"])
            scores[axis["axis_id"]] = st.selectbox(
                f"{axis['axis_id']} rating",
                options=score_options,
                index=_score_index(current),
                format_func=lambda value: "Not rated" if value is None else str(value),
                key=f"score::{annotator_id}::{item.blinded_item_id}::{axis['axis_id']}",
            )
            with st.expander(f"{axis['axis_id']} score anchors"):
                for score, anchor in sorted(axis["anchors"].items()):
                    st.markdown(f"**{score}:** {anchor}")
        notes = st.text_area(
            "Annotation notes",
            value=latest.notes if latest else "",
            key=f"notes::{annotator_id}::{item.blinded_item_id}",
        )
        uncertain = st.checkbox(
            "Uncertain / adjudication needed",
            value=latest.uncertain_adjudication_needed if latest else False,
            key=f"uncertain::{annotator_id}::{item.blinded_item_id}",
        )
        save = st.form_submit_button("Save annotation progress", type="primary")
    if save:
        try:
            store.save(
                item,
                annotator_id=annotator_id,
                scores=AxisScores.model_validate(scores),
                notes=notes,
                uncertain_adjudication_needed=uncertain,
            )
        except (AnnotationError, AnnotationPersistenceError, ValueError) as error:
            st.error(str(error))
        else:
            st.success(
                "Annotation revision appended safely. Existing evidence was not overwritten."
            )

    try:
        export_frame = tidy_annotation_frame(store.read_events(), latest_only=True)
    except AnnotationPersistenceError as error:
        st.error(str(error))
    else:
        if not export_frame.empty:
            st.download_button(
                "Download blinded tidy annotation CSV",
                data=export_frame.to_csv(index=False),
                file_name="blinded_annotations.csv",
                mime="text/csv",
            )


def render_nlp() -> None:
    st.header("NLP Explorer")
    st.write(
        "All features below are deterministic, transparent, and calculated offline from saved assistant text. They are exploratory lexical signals, not clinical labels and not substitutes for human annotation."
    )
    records, load_errors = load_available_records()
    if load_errors:
        st.warning("Some malformed or incomplete raw directories were excluded.")
    if not records:
        st.info(
            "No assistant responses are available. Run an offline fixture or technical pilot to populate this explorer."
        )
        return
    status_banner(records)
    response_frame = conversation_records_to_frame(records)
    if response_frame.empty:
        st.info("The saved runs contain no successful response observations.")
        return
    try:
        features = extract_response_features(response_frame)
    except (KeyError, ValueError) as error:
        st.error(f"NLP features could not be calculated: {error}")
        return

    metric_columns = st.columns(4)
    metric_columns[0].metric("Responses", len(features))
    metric_columns[1].metric("Conversations", features["run_id"].nunique())
    metric_columns[2].metric("Mean words", f"{features['word_count'].mean():.1f}")
    metric_columns[3].metric(
        "Mean lexical drift",
        f"{features['lexical_drift'].dropna().mean():.3f}"
        if features["lexical_drift"].notna().any()
        else "N/A",
    )

    interpretable = [
        "run_id",
        "data_status",
        "model_slot",
        "context_condition",
        "turn_number",
        "word_count",
        "sentence_count",
        "lexical_diversity",
        "certainty_density_per_100_words",
        "uncertainty_alternatives_density_per_100_words",
        "endorsement_density_per_100_words",
        "grounding_density_per_100_words",
        "action_advice_density_per_100_words",
        "discouragement_refusal_density_per_100_words",
        "support_wellbeing_density_per_100_words",
        "response_user_tfidf_similarity",
        "turn_to_turn_tfidf_similarity",
        "lexical_drift",
    ]
    available = [column for column in interpretable if column in features]
    st.subheader("Response feature table")
    st.dataframe(features[available], hide_index=True, width="stretch")

    density_columns = [column for column in available if column.endswith("density_per_100_words")]
    if density_columns:
        selected_signal = st.selectbox("Lexical signal trajectory", density_columns)
        figure = px.line(
            features.sort_values(["run_id", "turn_number"]),
            x="turn_number",
            y=selected_signal,
            color="run_id",
            markers=True,
            labels={"turn_number": "Turn", selected_signal: "Markers per 100 words"},
        )
        figure.update_layout(legend_title_text="Conversation")
        st.plotly_chart(figure, width="stretch")

    st.subheader("Top TF-IDF terms")
    grouping_options = [
        column
        for column in ("model_slot", "presentation_level", "turn_number", "context_condition")
        if column in response_frame
    ]
    grouping = st.multiselect(
        "Group terms by",
        options=grouping_options,
        default=["model_slot"] if "model_slot" in grouping_options else [],
    )
    terms = top_tfidf_terms(
        response_frame,
        text_col="response_text",
        group_cols=tuple(grouping),
        top_n=8,
        min_documents=2,
    )
    if terms.empty:
        st.info("At least two usable responses per selected group are required for term summaries.")
    else:
        st.dataframe(terms, hide_index=True, width="stretch")

    st.subheader("Offline TF-IDF response map")
    projection = project_responses_2d(response_frame)
    if projection.empty:
        st.info(projection.attrs.get("reason", "A response map is not available."))
    else:
        map_figure = px.scatter(
            projection,
            x="svd_x",
            y="svd_y",
            color="model_slot",
            symbol="context_condition",
            hover_data=["run_id", "turn_number", "presentation_level"],
            labels={"svd_x": "SVD component 1", "svd_y": "SVD component 2"},
        )
        st.plotly_chart(map_figure, width="stretch")
    st.download_button(
        "Download NLP feature CSV",
        data=features.to_csv(index=False),
        file_name="offline_nlp_features.csv",
        mime="text/csv",
    )


def _latest_analysis_rows(
    configuration: LocalConfiguration,
    records: Sequence[ConversationRecord],
    events: Sequence[AnnotationEvent],
    annotator_id: str,
) -> pd.DataFrame:
    """Internally rejoin blinded scores for analysis; never used in annotation UI."""
    _, mapping = _blinding_material(configuration, records)
    map_by_item = {entry.blinded_item_id: entry for entry in mapping}
    record_lookup = records_by_run_id(records)
    rows: list[dict[str, Any]] = []
    for event in events:
        if event.annotator_id != annotator_id:
            continue
        entry = map_by_item.get(event.blinded_item_id)
        if entry is None:
            continue
        record = record_lookup.get(entry.run_id)
        if record is None:
            continue
        header = record.header
        rows.append(
            {
                "run_id": entry.run_id,
                "turn_number": entry.turn_number,
                "script_id": header.script_id,
                "theme": header.theme.value,
                "presentation_level": header.presentation_level.value,
                "model_slot": header.model_slot,
                "context_condition": header.context_condition.value,
                "repetition": header.repetition,
                "data_status": header.data_status,
                **event.scores.model_dump(),
            }
        )
    return pd.DataFrame(rows)


def render_trajectory(configuration: LocalConfiguration) -> None:
    st.header("Trajectory Analysis")
    st.info(
        "TECHNICAL PILOT / DEMO DESCRIPTIVE VIEW — no turn-level independence assumptions and no significance claims."
    )
    records, load_errors = load_available_records()
    if load_errors:
        st.warning("Some raw records were unavailable and excluded.")
    if not records:
        st.info("No conversations are available. Run a fixture and annotate responses first.")
        return
    try:
        store = AnnotationStore(ANNOTATION_LOG)
        events = store.latest_events()
    except AnnotationPersistenceError as error:
        st.error(str(error))
        return
    if not events:
        st.info(
            "No annotation ratings are available. Save at least one blinded A1/A2/A3 rating to calculate trajectories."
        )
        return
    annotators = sorted({event.annotator_id for event in events})
    annotator = st.selectbox("Annotation set", options=annotators)
    rows = _latest_analysis_rows(configuration, records, events, annotator)
    if rows.empty:
        st.info("No saved ratings could be matched to the currently available raw records.")
        return
    represented = [record for record in records if record.header.run_id in set(rows["run_id"])]
    status_banner(represented)

    primary_long = rows.melt(
        id_vars=["run_id", "turn_number"],
        value_vars=["A1", "A2", "A3"],
        var_name="Primary axis",
        value_name="Ordinal rating",
    ).dropna(subset=["Ordinal rating"])
    if primary_long.empty:
        st.info("Primary A1/A2/A3 ratings are still missing for this annotation set.")
    else:
        figure = px.line(
            primary_long.sort_values(["run_id", "turn_number"]),
            x="turn_number",
            y="Ordinal rating",
            color="Primary axis",
            line_dash="run_id",
            markers=True,
            category_orders={"Primary axis": ["A1", "A2", "A3"]},
            labels={"turn_number": "Turn"},
        )
        figure.update_yaxes(tickmode="array", tickvals=[0, 1, 2], range=[-0.1, 2.1])
        st.plotly_chart(figure, width="stretch")

    safety_threshold = int(configuration.rubric.safety_thresholds.get("A3", 2))
    summaries = summarize_conversations(
        rows,
        safety_threshold=safety_threshold,
        expected_turns=6,
    )
    headline_columns = st.columns(4)
    headline_columns[0].metric("Conversations", len(summaries))
    headline_columns[1].metric("Complete primary trajectories", int(summaries["is_complete"].sum()))
    headline_columns[2].metric(
        "Any observed A1=2",
        int(summaries["any_A1_2"].fillna(False).astype(bool).sum()),
    )
    headline_columns[3].metric(
        "Mean primary completeness",
        f"{summaries['completeness_rate'].mean() * 100:.1f}%",
    )
    summary_columns = [
        "run_id",
        "data_status",
        "mean_A1",
        "mean_A2",
        "mean_A3",
        "max_A1",
        "max_A2",
        "first_A1_2_turn",
        "first_A3_safety_turn",
        "persistence_after_onset_rate",
        "recovery_after_high_risk_turn",
        "final_A1",
        "final_A2",
        "final_A3",
        "completeness_rate",
    ]
    st.subheader("Conversation-level summaries")
    st.dataframe(
        summaries[[column for column in summary_columns if column in summaries]],
        hide_index=True,
        width="stretch",
    )

    st.subheader("Matched descriptive comparisons")
    comparisons = matched_descriptive_comparisons(summaries)
    if comparisons.empty or not comparisons["n_pairs"].gt(0).any():
        st.info(
            "Matched model/context comparisons require ratings for corresponding script and repetition cells. No complete matched comparison is available yet."
        )
    else:
        st.dataframe(
            comparisons[comparisons["n_pairs"] > 0],
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "Differences are level B minus level A and are descriptive. Conversations—not turns—are the analysis units."
        )
    st.download_button(
        "Download conversation trajectory CSV",
        data=summaries.to_csv(index=False),
        file_name="conversation_trajectory_summaries.csv",
        mime="text/csv",
    )


def render_qa(configuration: LocalConfiguration) -> None:
    st.header("Reproducibility & QA")
    st.write(
        "This view reports locally inspectable configuration, manifest coverage, hashes, and validation commands. It does not contact a model provider."
    )

    configuration_rows = [
        ("Study version", STUDY_VERSION, "frozen code constant"),
        (
            "Models configuration",
            configuration.models.version,
            canonical_hash(configuration.models),
        ),
        (
            "Generation configuration",
            configuration.models.generation.version,
            canonical_hash(configuration.models.generation),
        ),
        ("Rubric", configuration.rubric.version, canonical_hash(configuration.rubric)),
        ("Configuration bundle", configuration.models.version, configuration.bundle_hash),
    ]
    st.subheader("Configuration versions and SHA-256 hashes")
    st.dataframe(
        pd.DataFrame(configuration_rows, columns=["Component", "Version", "SHA-256"]),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        f"Model catalogue last checked in configuration: {configuration.models.catalogue_checked_at_utc.isoformat()}"
    )

    st.subheader("Manifest validation")
    try:
        manifest_rows = generate_manifest(list(configuration.scripts), configuration.models)
        manifest_errors = validate_manifest(manifest_rows)
        manifest = manifest_dataframe(manifest_rows)
    except (ConfigurationError, ValueError) as error:
        st.error(f"Manifest could not be generated: {error}")
        manifest = pd.DataFrame()
        manifest_errors = [str(error)]
    if manifest_errors:
        st.error("Manifest validation failed: " + "; ".join(manifest_errors))
    else:
        validation_columns = st.columns(4)
        validation_columns[0].metric("Rows", len(manifest))
        validation_columns[1].metric("Unique run IDs", manifest["run_id"].nunique())
        validation_columns[2].metric("Scripts", manifest["script_id"].nunique())
        validation_columns[3].metric("Balanced cells", "Yes")
        st.success("The locally generated 3×3×2×2×2 manifest contains 72 unique balanced rows.")
        st.dataframe(manifest, hide_index=True, width="stretch")
        st.download_button(
            "Download generated manifest CSV",
            data=manifest.to_csv(index=False),
            file_name="experiment_manifest.csv",
            mime="text/csv",
        )

    records, raw_errors = load_available_records()
    st.subheader("Local data completeness")
    data_metrics = st.columns(4)
    data_metrics[0].metric("Readable raw runs", len(records))
    data_metrics[1].metric(
        "Completed six-turn runs", sum(len(record.turns) == 6 for record in records)
    )
    data_metrics[2].metric("Stored successful turns", sum(len(record.turns) for record in records))
    data_metrics[3].metric("Raw load errors", len(raw_errors))
    if raw_errors:
        with st.expander("Raw data QA errors"):
            st.code("\n".join(raw_errors))

    st.subheader("Exact Windows PowerShell commands")
    st.code(
        'cd "C:\\Users\\Moham\\OneDrive\\Documents\\project"\n'
        ".\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt\n"
        ".\\.venv\\Scripts\\python.exe -m pytest -q\n"
        ".\\.venv\\Scripts\\python.exe -m streamlit run app.py",
        language="powershell",
    )
    st.markdown(
        "**Optional live technical pilot environment (never paste a real key into source files)**"
    )
    st.code(
        '$env:OPENROUTER_API_KEY = "<paste-key-in-your-private-terminal>"\n'
        '$env:OPENROUTER_MODEL_A = "<exact-model-a-slug>"\n'
        '$env:OPENROUTER_MODEL_B = "<exact-model-b-slug>"\n'
        ".\\.venv\\Scripts\\python.exe -m streamlit run app.py",
        language="powershell",
    )
    st.caption(
        "Normal app startup, tests, manifest generation, dry-run preview, NLP, and fixture execution remain offline. Live access is gated in Experiment Runner."
    )


def render_view(view: str, configuration: LocalConfiguration) -> None:
    if view == "Study Overview":
        render_overview(configuration)
    elif view == "Experiment Runner":
        render_runner(configuration)
    elif view == "Transcript & Provenance":
        render_provenance()
    elif view == "Blinded Annotation":
        render_annotation(configuration)
    elif view == "NLP Explorer":
        render_nlp()
    elif view == "Trajectory Analysis":
        render_trajectory(configuration)
    elif view == "Reproducibility & QA":
        render_qa(configuration)
    else:  # pragma: no cover - defensive guard for programmatic misuse
        raise ValueError(f"Unknown view: {view}")


def main() -> None:
    st.set_page_config(
        page_title="Controlled Multi-Turn LLM Safety Benchmark",
        page_icon=None,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        .block-container {max-width: 1180px; padding-top: 2rem; padding-bottom: 3rem;}
        [data-testid="stSidebar"] {border-right: 1px solid #d7dde5;}
        [data-testid="stMetric"] {border: 1px solid #d7dde5; padding: 0.8rem; border-radius: 0.35rem;}
        h1, h2, h3 {letter-spacing: -0.015em;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    initialise_state()
    st.sidebar.title("Research workspace")
    view = st.sidebar.radio("View", options=VIEWS, key="navigation")
    st.sidebar.divider()
    st.sidebar.caption("Protocol: six fixed turns · local-first · append-only evidence")
    st.sidebar.caption("Synthetic benchmark; not a clinical system")
    render_global_header(view)
    try:
        configuration = load_local_configuration()
    except ConfigurationError as error:
        st.error(f"Local configuration could not be loaded: {error}")
        st.stop()
    render_view(view, configuration)


if __name__ == "__main__":
    main()
