from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

import segment_bytes

from chamber_ctl.subsystems.exposure_controller import ExposureSettings
from ipi_ecs.subsystems.experiment_controller import RunState

from ipi_webview.dds.models import (
    BatchControllerAttempt,
    BatchControllerPlanEntry,
    BatchControllerState,
    ExperimentPhase,
    ExperimentReason,
    ExperimentRun,
    ExperimentState,
    ExposureSettingsData,
    QueueItem,
)


def decode_batch_controller_state(payload: bytes) -> BatchControllerState:
    from chamber_ctl.subsystems.batch_controller import decode_batch_state

    value = decode_batch_state(_as_bytes(payload, "Batch Controller state"))
    active = value.get("active_manifest")
    display = active if isinstance(active, dict) else value.get("display_manifest")
    assessment = value.get("assessment")
    decision = assessment.get("decision") if isinstance(assessment, dict) else None
    progress_rows = assessment.get("progress", []) if isinstance(assessment, dict) else []
    progress_by_sample = {
        row.get("sample"): row
        for row in progress_rows
        if isinstance(row, dict) and isinstance(row.get("sample"), int)
    }

    plan_entries = []
    if isinstance(display, dict):
        plan = display.get("plan")
        raw_entries = plan.get("entries", []) if isinstance(plan, dict) else []
        for order, entry in enumerate(raw_entries, start=1):
            if not isinstance(entry, dict):
                raise ValueError("Batch plan entry must be an object.")
            sample = int(entry["sample"])
            progress = progress_by_sample.get(sample, {})
            plan_entries.append(
                BatchControllerPlanEntry(
                    order=order,
                    sample_slot=sample,
                    mode=str(entry["mode"]),
                    target=float(entry["target"]),
                    state=str(progress.get("state", "planned")),
                    cumulative_dose=float(progress.get("cumulative_dose", 0.0)),
                    cumulative_runtime=float(progress.get("cumulative_runtime", 0.0)),
                    attempt_count=int(progress.get("attempt_count", 0)),
                    remainder=float(progress.get("remainder", entry["target"])),
                    overshoot=float(progress.get("overshoot", 0.0)),
                )
            )

    attempts = []
    for attempt in value.get("attempts", []):
        if not isinstance(attempt, dict):
            raise ValueError("Batch attempt must be an object.")
        attempts.append(
            BatchControllerAttempt(
                run_uuid=UUID(str(attempt["run_uuid"])),
                sample_slot=None if attempt.get("sample") is None else int(attempt["sample"]),
                created_at=float(attempt["created_at"]),
                end_time=None if attempt.get("end_time") is None else float(attempt["end_time"]),
                status=None if attempt.get("status") is None else str(attempt["status"]),
                end_reason=None if attempt.get("end_reason") is None else str(attempt["end_reason"]),
                dose=None if attempt.get("dose") is None else float(attempt["dose"]),
                runtime=None if attempt.get("runtime") is None else float(attempt["runtime"]),
                snapshot_count=int(attempt.get("snapshot_count", 0)),
                validation_error=(
                    None if attempt.get("validation_error") is None else str(attempt["validation_error"])
                ),
            )
        )

    template = None
    if isinstance(display, dict) and isinstance(display.get("plan"), dict):
        template = display["plan"].get("template")
    return BatchControllerState(
        emitted_at=float(value["emitted_at"]),
        phase=str(value["phase"]),
        message=str(value.get("message", "")),
        last_error=None if value.get("last_error") is None else str(value["last_error"]),
        lease_owned=bool(value.get("lease_owned", False)),
        active_batch_uuid=(
            None if value.get("active_batch_uuid") is None else UUID(str(value["active_batch_uuid"]))
        ),
        name=str(template.get("name", "")) if isinstance(template, dict) else None,
        description=str(template.get("description", "")) if isinstance(template, dict) else None,
        revision=int(display["revision"]) if isinstance(display, dict) else None,
        manifest_status=str(display["status"]) if isinstance(display, dict) else None,
        mode=(
            str(value["execution_mode"])
            if value.get("execution_mode") in ("manual", "automatic")
            else str(display["mode"])
            if isinstance(display, dict)
            else None
        ),
        paused=bool(display["paused"]) if isinstance(display, dict) else None,
        cancel_pending=bool(display["cancel_pending"]) if isinstance(display, dict) else None,
        decision_kind=str(decision["kind"]) if isinstance(decision, dict) else None,
        decision_message=str(decision["message"]) if isinstance(decision, dict) else None,
        plan_entries=tuple(plan_entries),
        attempts=tuple(attempts),
    )


def _as_bytes(value: Any, field_name: str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview, list)):
        try:
            return bytes(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} is not byte-compatible.") from exc
    raise ValueError(f"{field_name} must be bytes.")


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _optional_float(value: Any, field_name: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric.") from exc


def _optional_int(value: Any, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc


def settings_from_mapping(settings: Mapping[str, Any]) -> ExposureSettingsData:
    return ExposureSettingsData(
        name=_text(settings.get("name")),
        description=_text(settings.get("description")),
        target_time=_optional_float(settings.get("target_time"), "target_time"),
        target_dose=_optional_float(settings.get("target_dose"), "target_dose"),
        operator=_text(settings.get("operator")),
        zr_filter=_text(settings.get("zr_filter")),
        sample_slot=_optional_int(settings.get("sample"), "sample"),
        sample_type=_text(settings.get("sample_type")),
        base_pressure=_optional_float(settings.get("base_pressure"), "base_pressure"),
        operating_pressure=_optional_float(settings.get("operating_pressure"), "operating_pressure"),
        flow_sccm=_optional_float(settings.get("flow_sccm"), "flow_sccm"),
    )


def decode_exposure_settings(payload: bytes) -> ExposureSettingsData:
    decoded = ExposureSettings.decode(_as_bytes(payload, "Exposure settings").decode("utf-8"))
    return settings_from_mapping(decoded.get_dict())


def decode_experiment_state(payload: bytes) -> ExperimentState:
    parts = segment_bytes.decode(_as_bytes(payload, "Exposure state"))
    if len(parts) != 2:
        raise ValueError(f"Exposure state must contain 2 segments, got {len(parts)}.")

    phase_bytes = _as_bytes(parts[0], "Exposure phase")
    if len(phase_bytes) == 0:
        raise ValueError("Exposure phase is empty.")

    try:
        phase = ExperimentPhase(int.from_bytes(phase_bytes, byteorder="big"))
    except ValueError as exc:
        raise ValueError("Exposure phase is unknown.") from exc

    if phase is ExperimentPhase.STOPPED:
        return ExperimentState(phase=phase, run=None)

    state_payload = _as_bytes(parts[1], "Run state")
    if len(state_payload) == 0:
        raise ValueError("An active experiment state is missing its run state.")

    run_state = RunState.decode(state_payload.decode("utf-8"))
    run_settings = settings_from_mapping(run_state.get_settings().get_dict())
    return ExperimentState(
        phase=phase,
        run=ExperimentRun(
            uuid=run_state.get_uuid(),
            experiment_type=run_state.get_type(),
            name=_text(run_state.get_name()),
            description=_text(run_state.get_description()),
            settings=run_settings,
        ),
    )


def decode_experiment_reasons(payload: bytes) -> tuple[ExperimentReason, ...]:
    reasons = []
    for encoded_reason in segment_bytes.decode(_as_bytes(payload, "Exposure reasons")):
        parts = segment_bytes.decode(_as_bytes(encoded_reason, "Exposure reason"))
        if len(parts) != 3:
            raise ValueError(f"Exposure reason must contain 3 segments, got {len(parts)}.")
        reasons.append(
            ExperimentReason(
                subsystem=_as_bytes(parts[0], "Reason subsystem").decode("utf-8", errors="replace"),
                status=_as_bytes(parts[1], "Reason status").decode("utf-8", errors="replace"),
                reason=_as_bytes(parts[2], "Reason text").decode("utf-8", errors="replace"),
            )
        )
    return tuple(reasons)


def decode_queue(payload: bytes) -> tuple[QueueItem, ...]:
    payload = _as_bytes(payload, "Exposure queue")
    if len(payload) == 0:
        return ()

    items = []
    for position, encoded_settings in enumerate(segment_bytes.decode(payload)):
        try:
            settings = decode_exposure_settings(_as_bytes(encoded_settings, "Queued exposure"))
        except Exception as exc:  # Preserve malformed entries without losing their queue position.
            items.append(QueueItem(position=position, settings=None, error=f"{type(exc).__name__}: {exc}"))
        else:
            items.append(QueueItem(position=position, settings=settings))
    return tuple(items)
