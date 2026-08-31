# ruff: noqa: E501
"""Local dashboard for the controlled six-turn benchmark.

Normal import and Streamlit startup are deliberately offline. Live technical workflows
remain behind the same evidence and confirmation gates as the command-line tools.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

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
    generation_for_model,
    load_histories,
    load_models,
    load_rubric,
    load_scripts,
    resolve_model_ids,
    validate_catalogue,
)
from src.conversation_runner import ConversationRunner, create_run_header
from src.main_study import (
    JobStatus,
    format_duration,
    launch_study_worker,
    load_study_progress,
    request_safe_stop,
    run_main_study_preflight,
    worker_is_active,
)
from src.manifest import STUDY_VERSION, generate_manifest, manifest_dataframe, validate_manifest
from src.nlp_features import (
    conversation_records_to_frame,
    extract_response_features,
    project_responses_2d,
    top_tfidf_terms,
)
from src.provider_client import DeterministicFixtureProvider
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
MAIN_STUDY_RAW_DIR = DATA_DIR / "raw" / "study-v2"
MAIN_STUDY_JOB_DIR = DATA_DIR / "private" / "main-study-job"
PILOT_V6_DIR = BASE_DIR / "data" / "private" / "technical-pilot-v6.0.0"
ACTIVE_BUNDLE_DIR = BASE_DIR / "protocol" / "study-v2.1.0"
GOVERNANCE_PATH = CONFIG_DIR / "main-study-governance.yaml"

MAIN_STUDY_BLOCKER_MESSAGES = {
    "active_bundle_not_created": "Active study bundle has not been created.",
    "active_bundle_invalid": "Active study bundle does not match the frozen study files.",
    "ethics_determination_pending": "Ethics determination is still pending.",
    "rubric_not_frozen": "Rubric has not yet been frozen.",
    "annotation_procedure_not_frozen": "Annotation procedure has not yet been frozen.",
    "data_management_not_confirmed": ("Data-management arrangements have not yet been confirmed."),
    "api_key_not_available": "OpenRouter API key is not available to the app process.",
    "main_study_worker_already_running": "Another main-study worker is already running.",
    "pilot_v6_not_pass": "Pilot V6 qualification does not currently recompute to PASS.",
}

VIEWS: tuple[str, ...] = (
    "Overview",
    "Collection",
    "Annotation",
    "Analysis",
    "Evidence & QA",
)

EXECUTION_MODES: tuple[str, ...] = (
    "Dry run (offline payload preview)",
    "Deterministic fixture (offline execution)",
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
        generation=(
            generation_for_model(configuration.models, model_slot, 1)
            if model_slot in configuration.models.model_slots
            else configuration.models.generation.model_copy(
                update={
                    "seed": configuration.models.repetition_seeds[1],
                    "completion_limit_parameter": "max_tokens",
                }
            )
        ),
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


def render_page_header(title: str, description: str | None = None) -> None:
    st.title(title)
    if description:
        st.caption(description)


def render_empty_state(message: str) -> None:
    with st.container(border=True):
        st.info(message)


def render_overview(configuration: LocalConfiguration) -> None:
    render_page_header(
        "LLM Response Behaviour Benchmark",
        "Controlled multi-turn evaluation of how language models respond to unsupported interpretations.",
    )

    metric_columns = st.columns(4)
    metric_columns[0].metric("Conversations", "72")
    metric_columns[1].metric("Planned responses", "432")
    metric_columns[2].metric("Models", "2")
    metric_columns[3].metric("Turns per conversation", "6")

    st.subheader("Research workflow")
    st.write("Study setup → Collection → Blinded annotation → Analysis → Evidence and reporting")

    st.subheader("Research questions")
    questions = (
        "RQ1 — How does presentation level affect belief-confirming and harm-enabling responses across a six-turn exchange?",
        "RQ2 — How do MiniMax M3 and NVIDIA Nemotron 3 Super differ on the primary A1, A2, and A3 outcomes under the qualified generation-v4 configuration?",
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
    st.subheader("Experimental design")
    st.write("3 presentation levels × 3 themes × 2 models × 2 contexts × 2 repetitions")
    with st.expander("View full study design"):
        st.dataframe(design, hide_index=True, width="stretch")
        st.caption(
            f"Configuration {configuration.models.version}; generation {configuration.models.generation.version}; rubric {configuration.rubric.version} ({configuration.rubric.status})."
        )

    st.divider()
    st.caption(
        "This research prototype uses synthetic inputs. It is not a clinical or diagnostic system."
    )


def _selection_controls(
    configuration: LocalConfiguration,
) -> tuple[ScriptConfig, ContextCondition, str, str, str]:
    script_lookup = {script.script_id: script for script in configuration.scripts}
    mode = st.selectbox("Execution mode", options=EXECUTION_MODES)
    model_slot = ""
    fixture_profile = "safe"
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
    if mode == EXECUTION_MODES[1]:
        fixture_profile = st.selectbox(
            "Fixture response profile",
            options=("safe", "risk_prone"),
            format_func=lambda value: value.replace("_", " ").title(),
        )
    elif mode == EXECUTION_MODES[0]:
        model_slot = st.selectbox(
            "Target model slot",
            options=tuple(configuration.models.model_slots),
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
    st.subheader("Offline Sandbox")
    st.write(
        "Preview requests or run a deterministic fixture for development and QA. This is not main-study collection."
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
                    generation=generation_for_model(configuration.models, model_slot, 1),
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


def _main_study_preflight(environ: dict[str, str] | None = None):  # noqa: ANN202
    return run_main_study_preflight(
        repository_root=BASE_DIR,
        raw_root=MAIN_STUDY_RAW_DIR,
        job_root=MAIN_STUDY_JOB_DIR,
        pilot_v6_root=PILOT_V6_DIR,
        active_bundle_root=ACTIVE_BUNDLE_DIR,
        governance_path=GOVERNANCE_PATH,
        environ=environ,
    )


def _render_collection_status(status: str) -> None:
    renderer = {
        "NOT READY": st.warning,
        "READY": st.success,
        "RUNNING": st.info,
        "RESUMING": st.info,
        "WAITING TO RETRY": st.warning,
        "STOPPED": st.info,
        "BLOCKED": st.error,
        "COMPLETE": st.success,
    }[status]
    renderer(f"Study status: {status}")


@st.fragment(run_every=5)
def _render_main_study_progress(preflight_ready: bool = False) -> None:
    # Streamlit reruns often, so progress is always reconstructed from disk.
    try:
        progress = load_study_progress(
            repository_root=BASE_DIR,
            raw_root=MAIN_STUDY_RAW_DIR,
            state_path=MAIN_STUDY_JOB_DIR / "state.json",
        )
    except (OSError, RuntimeError, ValueError) as error:
        st.error(f"Saved main-study progress is not readable: {error}")
        return

    display_status = progress.status.value.replace("_", " ")
    if progress.status == JobStatus.NOT_STARTED:
        display_status = "READY" if preflight_ready else "NOT READY"
    _render_collection_status(display_status)

    metrics = st.columns(4)
    metrics[0].metric(
        "Conversations", f"{progress.conversations_complete} / {progress.conversations_planned}"
    )
    metrics[1].metric("Responses", f"{progress.responses_complete} / {progress.responses_planned}")
    metrics[2].metric("Technical API errors", progress.technical_errors)
    metrics[3].metric("Automatic recoveries", progress.automatic_resumes)
    st.progress(
        min(1.0, progress.percent_complete / 100), text=f"{progress.percent_complete:.1f}% complete"
    )

    detail = st.columns(3)
    detail[0].metric(
        "Current conversation",
        (
            f"{progress.current_execution_order} / {progress.conversations_planned}"
            if progress.current_execution_order is not None
            else "—"
        ),
    )
    detail[1].metric(
        "Current turn", f"{progress.current_turn} / 6" if progress.current_turn else "—"
    )
    detail[2].metric(
        "Current model",
        (progress.current_model_slot or "—").replace("model_", "").title(),
    )
    timing = st.columns(3)
    timing[0].metric("Elapsed", format_duration(progress.elapsed_seconds))
    timing[1].metric(
        "Estimated remaining",
        (
            "calculating..."
            if progress.estimated_remaining_seconds is None
            else "~" + format_duration(progress.estimated_remaining_seconds)
        ),
    )
    timing[2].metric("Truncations", progress.truncations)

    if progress.status == JobStatus.COMPLETE:
        st.success("MAIN STUDY COLLECTION COMPLETE")
        st.write(
            "Collection is complete. Validate the saved evidence before beginning annotation or analysis."
        )
        counts = progress.response_counts_by_model
        st.write(f"MiniMax responses: {counts.get('minimax/minimax-m3:free', 0)}")
        st.write(f"Nemotron responses: {counts.get('nvidia/nemotron-3-super-120b-a12b:free', 0)}")
    elif progress.status == JobStatus.WAITING_TO_RETRY:
        remaining = None
        if progress.next_retry_at is not None:
            remaining = max(0, round((progress.next_retry_at - datetime.now(UTC)).total_seconds()))
        st.warning(
            "Temporary API error. "
            + (
                f"Automatically resuming in about {remaining} seconds."
                if remaining is not None
                else "The worker will resume automatically."
            )
        )
    elif progress.status == JobStatus.BLOCKED:
        st.error(progress.message or "Collection is blocked and requires review.")
    elif progress.status == JobStatus.STOPPED:
        st.info(progress.message or "Collection stopped safely and can resume from disk.")
    try:
        active = worker_is_active(MAIN_STUDY_JOB_DIR)
    except (OSError, RuntimeError, ValueError):
        active = False
    if active and progress.status in {
        JobStatus.RUNNING,
        JobStatus.RESUMING,
        JobStatus.WAITING_TO_RETRY,
    }:
        if st.button("Stop safely"):
            request_safe_stop(MAIN_STUDY_JOB_DIR)
            st.info("A safe stop was requested. The current request will finish first.")


def render_main_study() -> None:
    render_page_header(
        "Main Study Collection",
        "Run the frozen study and follow progress saved by the background worker.",
    )
    st.caption(
        "Refreshing or closing this page does not restart collection. Successful responses are saved to disk before the next turn begins."
    )

    current = _main_study_preflight(dict(os.environ))
    saved = st.session_state.get("main_study_preflight")
    if saved:
        from src.main_study import StudyPreflight

        current = StudyPreflight.model_validate(saved)

    _render_main_study_progress(current.ready)

    with st.container(border=True):
        st.subheader("Study readiness")
        if current.ready:
            st.success("All machine-readable preflight requirements are complete.")
        else:
            st.markdown("**Needs attention**")
            for blocker in current.blockers:
                st.markdown(f"○ {MAIN_STUDY_BLOCKER_MESSAGES.get(blocker, blocker)}")

        if st.button("Run preflight", type="primary"):
            load_dotenv(BASE_DIR / ".env", override=False)
            current = _main_study_preflight(dict(os.environ))
            st.session_state["main_study_preflight"] = current.model_dump(mode="json")

    check_labels = {
        "expected_model_pair": "Exact model pair",
        "manifest_72_conversations": "72 unique conversations",
        "manifest_432_responses": "432 planned responses",
        "pilot_v6_pass": "Pilot V6 PASS",
        "storage_available": "Storage available",
        "saved_state_readable": "Saved study state readable",
        "no_active_worker": "No conflicting worker",
        "api_key_present": "API key available",
        "active_bundle_verified": "Active study bundle verified",
        "governance_complete": "Governance requirements complete",
        "main_study_ready": "Main-study readiness PASS",
    }
    with st.expander("Preflight details"):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Check": check_labels.get(name, name),
                        "Status": "PASS" if passed else "BLOCKED",
                    }
                    for name, passed in current.checks.items()
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        st.dataframe(
            pd.DataFrame(
                [
                    ("Pilot V6", current.pilot_v6),
                    ("Final pair source", current.final_pair_source),
                    ("Active bundle", current.active_bundle),
                    ("Governance", current.governance),
                    ("Main study", current.main_study),
                    ("Network requests during preflight", current.network_requests),
                ],
                columns=["Item", "Status"],
            ),
            hide_index=True,
            width="stretch",
        )

    st.subheader("Collection control")
    confirmed = st.checkbox(
        "I understand this starts the frozen main-study data collection.",
        disabled=not current.ready,
    )
    if not current.ready:
        st.caption("Start is disabled until all preflight requirements are complete.")
    if st.button("Start Main Study", disabled=not (current.ready and confirmed)):
        load_dotenv(BASE_DIR / ".env", override=False)
        fresh = _main_study_preflight(dict(os.environ))
        if not fresh.ready:
            st.error("Preflight changed. The study was not started.")
        else:
            try:
                pid = launch_study_worker(
                    repository_root=BASE_DIR,
                    job_root=MAIN_STUDY_JOB_DIR,
                    raw_root=MAIN_STUDY_RAW_DIR,
                    pilot_v6_root=PILOT_V6_DIR,
                    active_bundle_root=ACTIVE_BUNDLE_DIR,
                    governance_path=GOVERNANCE_PATH,
                    environ=dict(os.environ),
                )
            except (OSError, RuntimeError, ValueError) as error:
                st.error(f"The study worker could not start: {error}")
            else:
                st.success(f"Main-study worker started (process {pid}).")
                st.session_state.pop("main_study_preflight", None)

    with st.expander("Study configuration"):
        st.markdown("**Frozen model pair**")
        st.dataframe(
            pd.DataFrame(
                [
                    ("MiniMax M3", "minimax/minimax-m3:free"),
                    ("Nemotron 3 Super", "nvidia/nemotron-3-super-120b-a12b:free"),
                ],
                columns=["Model", "Exact endpoint"],
            ),
            hide_index=True,
            width="stretch",
        )
        st.caption("72 conversations · 432 planned responses · six turns per conversation")

    with st.expander("Technical run details"):
        try:
            progress = load_study_progress(
                repository_root=BASE_DIR,
                raw_root=MAIN_STUDY_RAW_DIR,
                state_path=MAIN_STUDY_JOB_DIR / "state.json",
            )
            st.write(f"HTTP attempts: {progress.http_attempts} / 576")
            st.write(f"Background worker active: {worker_is_active(MAIN_STUDY_JOB_DIR)}")
        except (OSError, RuntimeError, ValueError) as error:
            st.warning(f"Technical run details are unavailable: {error}")
        st.write(f"Pilot V6: {current.pilot_v6}")
        st.write(f"Final pair source: {current.final_pair_source}")
        st.write(f"Active bundle: {current.active_bundle}")
        st.write(f"Raw output: {MAIN_STUDY_RAW_DIR}")


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


def render_provenance(*, show_header: bool = True) -> None:
    if show_header:
        st.header("Runs & provenance")
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
            expanded=False,
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
            with st.expander(
                f"Turn {error.turn_number}: {error.result.error_type or 'unspecified error'}"
            ):
                st.write(f"Observation status: {error.result.status.value}")
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


def _score_index(value: int | str | None, options: list[int | str | None]) -> int:
    return options.index(value) if value in options else 0


def render_annotation(configuration: LocalConfiguration) -> None:
    render_page_header(
        "Blinded Annotation",
        "Score saved main-study responses without model or condition information.",
    )
    records, load_errors = load_available_records(RawRunStore(MAIN_STUDY_RAW_DIR))
    records = [record for record in records if record.header.data_status == "main_study"]
    if load_errors:
        st.warning("Some unavailable raw records were excluded from item preparation.")
    if not records:
        render_empty_state(
            "Annotation becomes available after validated main-study responses have been prepared."
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
    progress_columns = st.columns(4)
    progress_columns[0].metric("Items", len(items))
    progress_columns[1].metric("Complete", complete_count)
    progress_columns[2].metric("Remaining", max(0, len(items) - complete_count))
    progress_columns[3].metric("Current round", items[0].rating_round.replace("_", " ").title())

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

    context_column, scoring_column = st.columns([1.15, 1], gap="large")
    with context_column:
        st.caption(
            f"Item: {item.blinded_item_id} · Round: {item.rating_round} · Turn: {item.turn_number}"
        )
        st.subheader("Conversation context")
        for message in item.conversation_context:
            with st.container(border=True):
                st.caption(message.role.upper())
                st.write(message.content)
        with st.container(border=True):
            st.markdown("**Response to score**")
            st.write(item.response_to_score)

    rubric_rows = rubric_display_rows(configuration.rubric)
    saved_scores = latest.scores.model_dump() if latest else {}
    with scoring_column:
        st.subheader("Scoring form")
        st.caption(
            f"Rubric {configuration.rubric.version} ({configuration.rubric.status}). Not rated and N/A are distinct."
        )
        with st.form(f"annotation::{annotator_id}::{item.blinded_item_id}"):
            scores: dict[str, int | str | None] = {}
            for axis in rubric_rows:
                if axis["axis_id"] == "A1":
                    st.markdown("### Primary outcomes")
                elif axis["axis_id"] == "B1":
                    st.markdown("### Exploratory outcomes")
                st.markdown(
                    f"**{axis['axis_id']} — {axis['name']}** · higher is {axis['direction']}"
                )
                st.caption(axis["definition"])
                current = saved_scores.get(axis["axis_id"])
                score_options: list[int | str | None] = [None, *axis["allowed_scores"]]
                if axis["allows_na"]:
                    score_options.append("N/A")
                scores[axis["axis_id"]] = st.selectbox(
                    f"{axis['axis_id']} rating",
                    options=score_options,
                    index=_score_index(current, score_options),
                    format_func=lambda value: "Not rated" if value is None else str(value),
                    key=f"score::{annotator_id}::{item.blinded_item_id}::{axis['axis_id']}",
                )
                with st.expander(f"{axis['axis_id']} score anchors"):
                    if axis["na_guidance"]:
                        st.markdown(f"**N/A:** {axis['na_guidance']}")
                    for score, anchor in sorted(axis["anchors"].items()):
                        st.markdown(f"**{score}:** {anchor}")
                    for note in axis["notes"]:
                        st.caption(note)
                    if axis["examples"]:
                        st.caption("Examples: " + "; ".join(axis["examples"]))
            notes = st.text_area(
                "Annotation notes",
                value=latest.notes if latest else "",
                key=f"notes::{annotator_id}::{item.blinded_item_id}",
            )
            uncertain = st.checkbox(
                "Uncertain / disagreement review needed",
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


def render_nlp(
    records: Sequence[ConversationRecord] | None = None,
    *,
    show_header: bool = True,
) -> None:
    if show_header:
        st.header("Exploratory NLP")
    st.write(
        "All features below are deterministic, transparent, and calculated offline from saved assistant text. They are exploratory lexical signals, not clinical labels and not substitutes for human annotation."
    )
    if records is None:
        records, load_errors = load_available_records()
    else:
        records = list(records)
        load_errors = []
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


def render_trajectory(
    configuration: LocalConfiguration,
    records: Sequence[ConversationRecord] | None = None,
    *,
    show_header: bool = True,
) -> None:
    if show_header:
        st.header("Trajectories")
    st.caption("Conversation-level descriptive analysis; turns are not independent units.")
    if records is None:
        records, load_errors = load_available_records()
    else:
        records = list(records)
        load_errors = []
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

    safety_threshold = int(configuration.rubric.safety_thresholds.get("A3", 1))
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


def render_primary_outcomes(
    configuration: LocalConfiguration,
    records: Sequence[ConversationRecord],
) -> None:
    if not records:
        render_empty_state("Results will appear after collection and blinded human annotation.")
        return
    try:
        events = AnnotationStore(ANNOTATION_LOG).latest_events()
    except AnnotationPersistenceError as error:
        st.error(str(error))
        return
    if not events:
        render_empty_state("No blinded human ratings are available yet.")
        return
    annotators = sorted({event.annotator_id for event in events})
    annotator = st.selectbox("Annotation set", options=annotators, key="primary_annotation_set")
    rows = _latest_analysis_rows(configuration, records, events, annotator)
    if rows.empty:
        render_empty_state("Saved ratings could not be matched to main-study responses.")
        return
    summaries = summarize_conversations(
        rows,
        safety_threshold=int(configuration.rubric.safety_thresholds.get("A3", 1)),
        expected_turns=6,
    )
    metrics = st.columns(3)
    metrics[0].metric("Rated conversations", len(summaries))
    metrics[1].metric("Complete trajectories", int(summaries["is_complete"].sum()))
    metrics[2].metric(
        "Mean annotation completeness", f"{summaries['completeness_rate'].mean() * 100:.1f}%"
    )
    st.dataframe(
        summaries[
            [
                "run_id",
                "mean_A1",
                "mean_A2",
                "mean_A3",
                "final_A1",
                "final_A2",
                "final_A3",
                "completeness_rate",
            ]
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption("A1, A2 and A3 remain separate primary outcomes. No combined score is used.")


def render_analysis(configuration: LocalConfiguration) -> None:
    render_page_header(
        "Analysis",
        "Human-rated outcomes are primary; lexical analysis remains exploratory.",
    )
    records, load_errors = load_available_records(RawRunStore(MAIN_STUDY_RAW_DIR))
    records = [record for record in records if record.header.data_status == "main_study"]
    if load_errors:
        st.warning("Some main-study records could not be read and analysis is unavailable.")
    primary_tab, trajectory_tab, nlp_tab = st.tabs(
        ["Primary outcomes", "Trajectories", "Exploratory NLP"]
    )
    with primary_tab:
        render_primary_outcomes(configuration, records)
    with trajectory_tab:
        if records:
            render_trajectory(configuration, records, show_header=False)
        else:
            render_empty_state("Trajectories will appear after collection and annotation.")
    with nlp_tab:
        if records:
            render_nlp(records, show_header=False)
        else:
            render_empty_state("Exploratory NLP will appear after main-study collection.")


def render_qa(configuration: LocalConfiguration, *, show_header: bool = True) -> None:
    if show_header:
        st.header("Configuration")
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
        with st.expander("View 72-row manifest"):
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
    st.caption(
        "App startup, tests, manifest preview, analysis and fixture execution remain offline. Main-study collection retains its separate readiness and confirmation gates."
    )


def render_study_audit() -> None:
    st.subheader("Study audit")
    try:
        progress = load_study_progress(
            repository_root=BASE_DIR,
            raw_root=MAIN_STUDY_RAW_DIR,
            state_path=MAIN_STUDY_JOB_DIR / "state.json",
        )
    except (OSError, RuntimeError, ValueError) as error:
        st.error(f"Main-study evidence could not be audited: {error}")
        return
    metrics = st.columns(4)
    metrics[0].metric("Conversations complete", f"{progress.conversations_complete} / 72")
    metrics[1].metric("Responses complete", f"{progress.responses_complete} / 432")
    metrics[2].metric("Technical errors", progress.technical_errors)
    metrics[3].metric("Truncations", progress.truncations)
    st.write(f"Current evidence status: {progress.status.value}")
    st.caption("Technical evidence and demo fixtures are not main-study results.")


def render_evidence(configuration: LocalConfiguration) -> None:
    render_page_header(
        "Evidence & QA",
        "Inspect saved runs, study checks, frozen configuration and offline tools.",
    )
    provenance_tab, audit_tab, configuration_tab, tools_tab = st.tabs(
        ["Runs & provenance", "Study audit", "Configuration", "Offline tools"]
    )
    with provenance_tab:
        render_provenance(show_header=False)
    with audit_tab:
        render_study_audit()
    with configuration_tab:
        render_qa(configuration, show_header=False)
    with tools_tab:
        render_runner(configuration)


def render_view(view: str, configuration: LocalConfiguration) -> None:
    if view == "Overview":
        render_overview(configuration)
    elif view == "Collection":
        render_main_study()
    elif view == "Annotation":
        render_annotation(configuration)
    elif view == "Analysis":
        render_analysis(configuration)
    elif view == "Evidence & QA":
        render_evidence(configuration)
    else:  # pragma: no cover - defensive guard for programmatic misuse
        raise ValueError(f"Unknown view: {view}")


def main() -> None:
    st.set_page_config(
        page_title="LLM Response Behaviour Benchmark",
        page_icon=None,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        .block-container {max-width: 1120px; padding-top: 1.75rem; padding-bottom: 3rem;}
        [data-testid="stSidebar"] {border-right: 1px solid rgba(128, 128, 128, 0.25);}
        h1, h2, h3 {letter-spacing: -0.015em;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    initialise_state()
    st.sidebar.markdown("### LLM Response Behaviour Benchmark")
    view = st.sidebar.radio("Research workspace", options=VIEWS, key="navigation")
    st.sidebar.divider()
    st.sidebar.caption("Study V2")
    st.sidebar.caption("Synthetic research benchmark")
    st.sidebar.caption("Not a clinical system")
    try:
        configuration = load_local_configuration()
    except ConfigurationError as error:
        st.error(f"Local configuration could not be loaded: {error}")
        st.stop()
    render_view(view, configuration)


if __name__ == "__main__":
    main()
