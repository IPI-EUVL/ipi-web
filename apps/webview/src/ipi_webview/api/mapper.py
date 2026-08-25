from __future__ import annotations

import time
from collections.abc import Callable
from uuid import UUID

from chamber_ctl.subsystems import uuids

from ipi_webview.api.models import (
    BatchExposureSummary,
    BatchPlanEntrySummary,
    BatchSlotSummary,
    BatchSummary,
    ExperimentDetails,
    ExperimentReason,
    ExperimentSummary,
    HealthState,
    IssueSeverity,
    LiveResponse,
    ProgressMode,
    ProgressSummary,
    PublicExperimentPhase,
    PublicStageState,
    QueueSummary,
    SourceState,
    SourceSummary,
    StagePosition,
    StageSummary,
    SubsystemIssue,
    SubsystemSummary,
    SystemIssue,
    SystemSummary,
)
from ipi_webview.api.settings import SUBSYSTEM_LABELS
from ipi_webview.batch.models import BatchExposure, BatchProjection, BatchSlotSummary as InternalBatchSlot
from ipi_webview.batch.models import LiveBatchSnapshot
from ipi_webview.dds.models import (
    ExperimentPhase,
    ObservedValue,
    StageState,
    StatusSeverity,
    SubsystemStatus,
)


_PHASES = {
    ExperimentPhase.CHECKING: PublicExperimentPhase.CHECKING,
    ExperimentPhase.PREPARING: PublicExperimentPhase.PREPARING,
    ExperimentPhase.INITIALIZING: PublicExperimentPhase.INITIALIZING,
    ExperimentPhase.RUNNING: PublicExperimentPhase.EXPOSING,
    ExperimentPhase.STOPPING: PublicExperimentPhase.STOPPING,
    ExperimentPhase.STOPPED: PublicExperimentPhase.IDLE,
}
_STAGE_STATES = {
    StageState.IDLE: PublicStageState.IDLE,
    StageState.HOMING: PublicStageState.HOMING,
    StageState.MOVING: PublicStageState.MOVING,
    StageState.OFFLINE: PublicStageState.OFFLINE,
}


def _sample_number(slot: int | None) -> int | None:
    if slot is None or slot < 0:
        return None
    return slot + 1


def _is_stale(observed_at: float | None, now: float, stale_after: float) -> bool:
    return observed_at is not None and now - observed_at > stale_after


def _source_summary(
    observed: ObservedValue,
    *,
    now: float,
    stale_after: float,
) -> SourceSummary:
    if observed.observed_at is None:
        state = SourceState.UNAVAILABLE
    elif _is_stale(observed.observed_at, now, stale_after):
        state = SourceState.STALE
    elif observed.error is not None:
        state = SourceState.DEGRADED
    else:
        state = SourceState.AVAILABLE
    return SourceSummary(
        state=state,
        observed_at=observed.observed_at,
        attempted_at=observed.attempted_at,
        error=observed.error,
    )


def _history_source(snapshot: LiveBatchSnapshot, now: float, stale_after: float) -> SourceSummary:
    history = snapshot.history
    if history.observed_at is None:
        state = SourceState.UNAVAILABLE
    elif _is_stale(history.observed_at, now, stale_after):
        state = SourceState.STALE
    elif history.error is not None:
        state = SourceState.DEGRADED
    else:
        state = SourceState.AVAILABLE
    return SourceSummary(
        state=state,
        observed_at=history.observed_at,
        attempted_at=history.attempted_at,
        error=history.error,
    )


def _combined_source(
    observed_values: tuple[ObservedValue, ...],
    *,
    now: float,
    stale_after: float,
) -> SourceSummary:
    observed_at = max(
        (observed.observed_at for observed in observed_values if observed.observed_at is not None),
        default=None,
    )
    attempted_at = max(
        (observed.attempted_at for observed in observed_values if observed.attempted_at is not None),
        default=None,
    )
    failed_attempts = [
        observed
        for observed in observed_values
        if observed.error is not None and observed.attempted_at is not None
    ]
    latest_failed_at = max((observed.attempted_at for observed in failed_attempts), default=None)
    errors = tuple(dict.fromkeys(observed.error for observed in failed_attempts if observed.error))

    if observed_at is None:
        state = SourceState.UNAVAILABLE
    elif _is_stale(observed_at, now, stale_after):
        state = SourceState.STALE
    elif latest_failed_at is not None and latest_failed_at >= observed_at:
        state = SourceState.DEGRADED
    else:
        state = SourceState.AVAILABLE
    return SourceSummary(
        state=state,
        observed_at=observed_at,
        attempted_at=attempted_at,
        error="; ".join(errors) or None,
    )


def _not_applicable_source(observed: ObservedValue) -> SourceSummary:
    return SourceSummary(
        state=SourceState.NOT_APPLICABLE,
        observed_at=observed.observed_at,
        attempted_at=observed.attempted_at,
        error=None,
    )


def _public_issue(item) -> SubsystemIssue | None:
    if item.severity is StatusSeverity.ALARM:
        return SubsystemIssue(severity=IssueSeverity.ERROR, message=item.message)
    if item.severity is StatusSeverity.WARNING:
        return SubsystemIssue(severity=IssueSeverity.WARNING, message=item.message)
    return None


def _primary_status(row: SubsystemStatus) -> str:
    for item in row.status_items:
        if item.code == 0 and item.message.strip():
            return item.message.strip()
    return "Connected" if row.connected else "Disconnected"


def _subsystems(
    rows: tuple[SubsystemStatus, ...] | None,
    critical_uuids: frozenset[UUID],
) -> tuple[SubsystemSummary, ...]:
    if rows is None:
        return ()
    return tuple(
        SubsystemSummary(
            name=row.name,
            critical=row.uuid in critical_uuids,
            connected=row.connected,
            primary_status=_primary_status(row),
            issues=tuple(issue for item in row.status_items if (issue := _public_issue(item)) is not None),
        )
        for row in rows
    )


def _system_summary(
    subsystem_rows: tuple[SubsystemStatus, ...] | None,
    public_subsystems: tuple[SubsystemSummary, ...],
    critical_uuids: frozenset[UUID],
    sources: dict[str, SourceSummary],
) -> SystemSummary:
    issues = []
    if sources["transport"].state is not SourceState.AVAILABLE:
        issues.append(
            SystemIssue(
                severity=IssueSeverity.ERROR,
                source="DDS server",
                message="The DDS server connection is unavailable or stale.",
            )
        )
    if sources["experiment"].state in (SourceState.STALE, SourceState.UNAVAILABLE):
        issues.append(
            SystemIssue(
                severity=IssueSeverity.ERROR,
                source="Exposure",
                message="Exposure status is unavailable or stale.",
            )
        )
    if sources["queue"].state in (SourceState.STALE, SourceState.UNAVAILABLE, SourceState.DEGRADED):
        issues.append(
            SystemIssue(
                severity=IssueSeverity.ERROR,
                source="Exposure queue",
                message="Exposure queue status is unavailable.",
            )
        )
    if sources["subsystems"].state in (SourceState.STALE, SourceState.UNAVAILABLE, SourceState.DEGRADED):
        issues.append(
            SystemIssue(
                severity=IssueSeverity.ERROR,
                source="Subsystems",
                message="Subsystem status is unavailable or stale.",
            )
        )
    rows_by_uuid = {row.uuid: row for row in subsystem_rows or ()}
    summaries_by_name = {row.name: row for row in public_subsystems}
    for subsystem_uuid in critical_uuids:
        row = rows_by_uuid.get(subsystem_uuid)
        if row is None:
            subsystem_name = SUBSYSTEM_LABELS.get(subsystem_uuid, "Configured required subsystem")
            issues.append(
                SystemIssue(
                    severity=IssueSeverity.ERROR,
                    source=subsystem_name,
                    message="A required subsystem is unavailable.",
                )
            )
            continue
        summary = summaries_by_name[row.name]
        if not row.connected:
            issues.append(
                SystemIssue(
                    severity=IssueSeverity.ERROR,
                    source=row.name,
                    message="Subsystem is disconnected.",
                )
            )
        for item in summary.issues:
            issues.append(SystemIssue(severity=item.severity, source=row.name, message=item.message))

    issues.sort(key=lambda issue: 0 if issue.severity is IssueSeverity.ERROR else 1)
    if any(issue.severity is IssueSeverity.ERROR for issue in issues):
        state = HealthState.ERROR
        label = "Errors reported"
    elif issues:
        state = HealthState.WARNING
        label = "Warnings reported"
    elif subsystem_rows is None:
        state = HealthState.UNKNOWN
        label = "System status unavailable"
    else:
        state = HealthState.OK
        label = "System OK"
    return SystemSummary(state=state, label=label, issues=tuple(issues))


def _experiment(snapshot: LiveBatchSnapshot) -> ExperimentSummary:
    state = snapshot.dds.experiment.value
    if state is None:
        return ExperimentSummary(phase=PublicExperimentPhase.IDLE, details=None, reasons=())
    run = state.run
    details = None
    if run is not None:
        settings = run.settings
        details = ExperimentDetails(
            run_id=run.uuid,
            name=run.name,
            description=run.description,
            operator=settings.operator,
            zr_filter=settings.zr_filter,
            sample_number=_sample_number(settings.sample_slot),
            sample_type=settings.sample_type,
            target_dose=settings.target_dose,
            target_time=settings.target_time,
            base_pressure=settings.base_pressure,
            operating_pressure=settings.operating_pressure,
            flow_sccm=settings.flow_sccm,
        )
    reasons = tuple(
        ExperimentReason(subsystem=reason.subsystem, status=reason.status, reason=reason.reason)
        for reason in (snapshot.dds.experiment_reasons.value or ())
    )
    return ExperimentSummary(phase=_PHASES[state.phase], details=details, reasons=reasons)


def _progress(snapshot: LiveBatchSnapshot) -> ProgressSummary:
    state = snapshot.dds.experiment.value
    if state is None or state.run is None:
        return ProgressSummary(mode=ProgressMode.NONE, current=None, target=None, unit=None, percent=None)
    settings = state.run.settings
    if settings.target_dose is not None and settings.target_dose > 0:
        mode = ProgressMode.DOSE
        current = snapshot.dds.current_dose.value
        target = settings.target_dose
        unit = "mJ/cm2"
    elif settings.target_time is not None and settings.target_time > 0:
        mode = ProgressMode.TIME
        current = snapshot.dds.current_time.value
        target = settings.target_time
        unit = "s"
    else:
        return ProgressSummary(
            mode=ProgressMode.INDETERMINATE,
            current=None,
            target=None,
            unit=None,
            percent=None,
        )
    percent = None if current is None else min(100.0, max(0.0, current / target * 100.0))
    return ProgressSummary(mode=mode, current=current, target=target, unit=unit, percent=percent)


def _batch_exposure(exposure: BatchExposure) -> BatchExposureSummary:
    return BatchExposureSummary(
        run_id=exposure.uuid,
        queue_position=None if exposure.queue_position is None else exposure.queue_position + 1,
        created_at=exposure.created_at,
        name=exposure.name,
        sample_number=_sample_number(exposure.sample_slot),
        target_dose=exposure.target_dose,
        target_time=exposure.target_time,
        actual_dose=exposure.actual_dose,
        actual_time=exposure.actual_time,
        state=exposure.state.value,
        status=exposure.status,
        end_reason=exposure.end_reason,
    )


def _batch_slot(slot: InternalBatchSlot) -> BatchSlotSummary:
    return BatchSlotSummary(
        sample_number=slot.sample_slot + 1,
        attempt_count=slot.attempt_count,
        first_target_dose=slot.first_target_dose,
        first_target_time=slot.first_target_time,
        cumulative_actual_dose=slot.cumulative_actual_dose,
        cumulative_actual_time=slot.cumulative_actual_time,
        state=slot.state.value,
        abort_reasons=slot.abort_reasons,
    )


def _batch(batch: BatchProjection) -> BatchSummary:
    return BatchSummary(
        name=batch.name,
        selection_source=batch.selection_source.value,
        exposures=tuple(_batch_exposure(exposure) for exposure in batch.exposures),
        slots=tuple(_batch_slot(slot) for slot in batch.slots),
        unplaced_exposures=tuple(_batch_exposure(exposure) for exposure in batch.unplaced_exposures),
        remaining_count=batch.matching_queue_count,
        possibly_truncated=batch.history_possibly_truncated,
    )


def _authoritative_batch(
    snapshot: LiveBatchSnapshot,
    *,
    now: float,
    stale_after: float,
) -> BatchSummary | None:
    observed = snapshot.dds.batch_controller
    state = observed.value
    if (
        state is None
        or observed.observed_at is None
        or _is_stale(observed.observed_at, now, stale_after)
    ):
        return None
    targets_by_sample = {entry.sample_slot: entry for entry in state.plan_entries}
    active_attempts = {
        attempt.sample_slot: attempt
        for attempt in state.attempts
        if attempt.sample_slot is not None and attempt.end_time is None
    }
    latest_terminal_attempts = {}
    for attempt in state.attempts:
        if attempt.sample_slot is None or attempt.end_time is None:
            continue
        previous = latest_terminal_attempts.get(attempt.sample_slot)
        if previous is None or (attempt.created_at, str(attempt.run_uuid)) > (previous.created_at, str(previous.run_uuid)):
            latest_terminal_attempts[attempt.sample_slot] = attempt

    experiment = snapshot.dds.experiment.value

    def live_actual(entry) -> float | None:
        attempt = active_attempts.get(entry.sample_slot)
        if attempt is None:
            return None
        if experiment is None or experiment.run is None or experiment.run.uuid != attempt.run_uuid:
            return None
        return (
            snapshot.dds.current_dose.value
            if entry.mode == "dose"
            else snapshot.dds.current_time.value
        )

    def planned_actual(entry) -> float | None:
        cumulative = entry.cumulative_dose if entry.mode == "dose" else entry.cumulative_runtime
        live = live_actual(entry)
        if live is not None:
            return cumulative + live
        if entry.sample_slot in active_attempts or entry.attempt_count == 0:
            return None
        return cumulative

    exposures = []
    for attempt in state.attempts:
        target = targets_by_sample.get(attempt.sample_slot)
        normalized_status = (attempt.status or "").strip().upper()
        if attempt.end_time is None:
            exposure_state = "current"
        elif normalized_status == "ABORTED":
            exposure_state = "failed"
        elif normalized_status == "STOPPED":
            final_for_sample = target is not None and latest_terminal_attempts.get(attempt.sample_slot) == attempt
            if final_for_sample and target.state == "overshot":
                exposure_state = "overshot"
            elif final_for_sample and target.state == "within_tolerance":
                exposure_state = "succeeded"
            else:
                exposure_state = "stopped"
        else:
            exposure_state = "unknown"
        exposures.append(
            BatchExposureSummary(
                run_id=attempt.run_uuid,
                queue_position=None,
                created_at=attempt.created_at,
                name=state.name or "",
                sample_number=_sample_number(attempt.sample_slot),
                target_dose=(target.target if target is not None and target.mode == "dose" else None),
                target_time=(target.target if target is not None and target.mode == "time" else None),
                actual_dose=(
                    attempt.dose
                    if attempt.dose is not None
                    else live_actual(target)
                    if attempt.end_time is None and target is not None and target.mode == "dose"
                    else None
                ),
                actual_time=(
                    attempt.runtime
                    if attempt.runtime is not None
                    else live_actual(target)
                    if attempt.end_time is None and target is not None and target.mode == "time"
                    else None
                ),
                state=exposure_state,
                status=attempt.status,
                end_reason=attempt.end_reason or attempt.validation_error,
            )
        )
    plan_entries = tuple(
        BatchPlanEntrySummary(
            order=entry.order,
            sample_number=entry.sample_slot + 1,
            mode=entry.mode,
            target=entry.target,
            cumulative_actual=planned_actual(entry),
            attempt_count=entry.attempt_count,
            state=entry.state,
            remainder=max(0.0, entry.remainder),
            overshoot=max(0.0, entry.overshoot),
        )
        for entry in state.plan_entries
    )
    slots = tuple(
        BatchSlotSummary(
            sample_number=entry.sample_slot + 1,
            attempt_count=entry.attempt_count,
            first_target_dose=entry.target if entry.mode == "dose" else None,
            first_target_time=entry.target if entry.mode == "time" else None,
            cumulative_actual_dose=entry.cumulative_dose,
            cumulative_actual_time=entry.cumulative_runtime,
            state=(
                "overshot"
                if entry.state == "overshot"
                else "succeeded"
                if entry.state == "within_tolerance"
                else "queued"
            ),
            abort_reasons=tuple(
                attempt.end_reason
                for attempt in state.attempts
                if attempt.sample_slot == entry.sample_slot
                and (attempt.status or "").strip().upper() == "ABORTED"
                and attempt.end_reason
            ),
        )
        for entry in state.plan_entries
    )
    return BatchSummary(
        name=state.name,
        selection_source="controller",
        exposures=tuple(exposures),
        slots=slots,
        unplaced_exposures=tuple(exposure for exposure in exposures if exposure.sample_number is None),
        remaining_count=sum(1 for entry in state.plan_entries if entry.state not in ("within_tolerance", "overshot")),
        possibly_truncated=False,
        authoritative=True,
        batch_id=state.active_batch_uuid,
        lease_owned=state.lease_owned,
        controller_phase=state.phase,
        controller_message=state.message,
        execution_mode=state.mode,
        manifest_status=state.manifest_status,
        revision=state.revision,
        paused=state.paused,
        cancel_pending=state.cancel_pending,
        decision_kind=state.decision_kind,
        decision_message=state.decision_message,
        plan_entries=plan_entries,
    )


def _stage(snapshot: LiveBatchSnapshot) -> StageSummary:
    stage_state = snapshot.dds.stage_state.value
    position = snapshot.dds.stage_position.value
    return StageSummary(
        state=_STAGE_STATES.get(stage_state, PublicStageState.UNKNOWN),
        current_sample_number=_sample_number(snapshot.dds.current_slot.value),
        position=None if position is None else StagePosition(theta=position[0], z=position[1]),
    )


class PublicSnapshotMapper:
    def __init__(
        self,
        critical_subsystem_uuids: frozenset[UUID],
        *,
        live_stale_after: float = 10.0,
        history_stale_after: float = 15.0,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._critical_subsystem_uuids = critical_subsystem_uuids
        self._live_stale_after = live_stale_after
        self._history_stale_after = history_stale_after
        self._wall_clock = wall_clock

    def map(self, snapshot: LiveBatchSnapshot) -> LiveResponse:
        now = self._wall_clock()
        dds = snapshot.dds
        subsystem_rows = dds.subsystems.value
        experiment_state = dds.experiment.value
        idle = experiment_state is None or experiment_state.run is None
        oscilloscope_connected = any(
            row.uuid == uuids.UUID_OSCILLOSCOPE_CONTROLLER and row.connected
            for row in subsystem_rows or ()
        )
        sources = {
            "transport": _source_summary(dds.transport_ready, now=now, stale_after=self._live_stale_after),
            "experiment": _source_summary(dds.experiment, now=now, stale_after=self._live_stale_after),
            "queue": _source_summary(dds.queue, now=now, stale_after=self._live_stale_after),
            "batch_controller": _source_summary(
                dds.batch_controller,
                now=now,
                stale_after=self._live_stale_after,
            ),
            "dose": (
                _not_applicable_source(dds.current_dose)
                if idle and oscilloscope_connected and dds.current_dose.value is None
                else _source_summary(dds.current_dose, now=now, stale_after=self._live_stale_after)
            ),
            "time": (
                _not_applicable_source(dds.current_time)
                if idle and oscilloscope_connected and dds.current_time.value is None
                else _source_summary(dds.current_time, now=now, stale_after=self._live_stale_after)
            ),
            "stage": _combined_source(
                (dds.stage_state, dds.stage_position, dds.current_slot),
                now=now,
                stale_after=self._live_stale_after,
            ),
            "subsystems": _source_summary(dds.subsystems, now=now, stale_after=self._live_stale_after),
            "history": _history_source(snapshot, now, self._history_stale_after),
        }
        public_subsystems = _subsystems(subsystem_rows, self._critical_subsystem_uuids)
        system = _system_summary(
            subsystem_rows,
            public_subsystems,
            self._critical_subsystem_uuids,
            sources,
        )
        raw_remaining = max(snapshot.batch.total_queue_count - int(snapshot.batch.queue_overlap_removed), 0)
        return LiveResponse(
            revision=snapshot.revision,
            generated_at=now,
            system=system,
            experiment=_experiment(snapshot),
            progress=_progress(snapshot),
            queue=QueueSummary(
                remaining_count=raw_remaining,
                current_batch_remaining_count=snapshot.batch.matching_queue_count,
            ),
            batch=_authoritative_batch(
                snapshot,
                now=now,
                stale_after=self._live_stale_after,
            )
            or _batch(snapshot.batch),
            stage=_stage(snapshot),
            subsystems=public_subsystems,
            sources=sources,
        )
