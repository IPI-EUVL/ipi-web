from __future__ import annotations

from collections.abc import Iterable

from ipi_webview.batch.models import (
    BatchExposure,
    BatchExposureState,
    BatchProjection,
    BatchSelectionSource,
    BatchSlotSummary,
    ExperimentHistoryRecord,
    ExperimentHistorySnapshot,
)
from ipi_webview.dds.models import DdsLiveSnapshot, ExperimentPhase, ExposureSettingsData


_PRE_RUNNING_PHASES = {
    ExperimentPhase.CHECKING,
    ExperimentPhase.PREPARING,
    ExperimentPhase.INITIALIZING,
}
_VALID_SAMPLE_SLOTS = range(12)
_USER_STOP_REASON = "stopped by user"


def _batch_name(value: str | None) -> str:
    return "" if value is None else value.strip()


def _settings_key(settings: ExposureSettingsData) -> tuple:
    return (
        settings.name.strip(),
        settings.description.strip(),
        settings.target_time,
        settings.target_dose,
        settings.operator.strip(),
        settings.zr_filter.strip(),
        settings.sample_slot,
        settings.sample_type.strip(),
        settings.base_pressure,
        settings.operating_pressure,
        settings.flow_sccm,
    )


def _select_name(
    dds: DdsLiveSnapshot,
    history: ExperimentHistorySnapshot,
) -> tuple[str | None, BatchSelectionSource]:
    experiment = dds.experiment.value
    if experiment is not None and experiment.run is not None:
        name = _batch_name(experiment.run.name)
        if name:
            return name, BatchSelectionSource.CURRENT_RUN

    queue_items = dds.queue.value or ()
    if queue_items and queue_items[0].settings is not None:
        name = _batch_name(queue_items[0].settings.name)
        if name:
            return name, BatchSelectionSource.QUEUE

    if history.records:
        name = _batch_name(history.records[0].name)
        if name:
            return name, BatchSelectionSource.HISTORY

    return None, BatchSelectionSource.NONE


def _target_missed(record: ExperimentHistoryRecord) -> bool:
    if record.target_dose is not None and record.target_dose > 0:
        return record.actual_dose is not None and record.actual_dose < record.target_dose
    if record.target_time is not None and record.target_time > 0:
        return record.actual_time is not None and record.actual_time < record.target_time
    return False


def _is_user_stop(reason: str | None) -> bool:
    return reason is not None and reason.strip().casefold().removesuffix(".").strip() == _USER_STOP_REASON


def _history_state(record: ExperimentHistoryRecord) -> BatchExposureState:
    if _is_user_stop(record.end_reason) and _target_missed(record):
        return BatchExposureState.FAILED
    normalized = "" if record.status is None else record.status.strip().upper()
    if normalized == "STOPPED":
        return BatchExposureState.SUCCEEDED
    if normalized == "ABORTED":
        return BatchExposureState.FAILED
    return BatchExposureState.UNKNOWN


def _history_exposure(record: ExperimentHistoryRecord) -> BatchExposure:
    return BatchExposure(
        uuid=record.uuid,
        queue_position=None,
        created_at=record.created_at,
        name=_batch_name(record.name),
        sample_slot=record.sample_slot,
        target_dose=record.target_dose,
        target_time=record.target_time,
        actual_dose=record.actual_dose,
        actual_time=record.actual_time,
        state=_history_state(record),
        status=record.status,
        end_reason=record.end_reason,
    )


def _current_exposure(dds: DdsLiveSnapshot, existing: BatchExposure | None = None) -> BatchExposure | None:
    experiment = dds.experiment.value
    if experiment is None or experiment.run is None:
        return None

    run = experiment.run
    settings = run.settings
    return BatchExposure(
        uuid=run.uuid,
        queue_position=None,
        created_at=existing.created_at if existing is not None else None,
        name=_batch_name(run.name),
        sample_slot=settings.sample_slot,
        target_dose=settings.target_dose,
        target_time=settings.target_time,
        actual_dose=dds.current_dose.value if dds.current_dose.value is not None else (
            existing.actual_dose if existing is not None else None
        ),
        actual_time=dds.current_time.value if dds.current_time.value is not None else (
            existing.actual_time if existing is not None else None
        ),
        state=BatchExposureState.CURRENT,
        status=existing.status if existing is not None else None,
        end_reason=existing.end_reason if existing is not None else None,
    )


def _queue_exposure(position: int, settings: ExposureSettingsData) -> BatchExposure:
    return BatchExposure(
        uuid=None,
        queue_position=position,
        created_at=None,
        name=_batch_name(settings.name),
        sample_slot=settings.sample_slot,
        target_dose=settings.target_dose,
        target_time=settings.target_time,
        actual_dose=None,
        actual_time=None,
        state=BatchExposureState.QUEUED,
        status=None,
        end_reason=None,
    )


def _slot_state(exposures: list[BatchExposure]) -> BatchExposureState:
    if any(exposure.state is BatchExposureState.CURRENT for exposure in exposures):
        return BatchExposureState.CURRENT
    if any(exposure.state is BatchExposureState.QUEUED for exposure in exposures):
        return BatchExposureState.QUEUED
    return exposures[-1].state


def _summarize_slots(
    exposures: Iterable[BatchExposure],
) -> tuple[tuple[BatchSlotSummary, ...], tuple[BatchExposure, ...]]:
    by_slot: dict[int, list[BatchExposure]] = {}
    unplaced = []
    for exposure in exposures:
        slot = exposure.sample_slot
        if slot not in _VALID_SAMPLE_SLOTS:
            unplaced.append(exposure)
            continue
        by_slot.setdefault(slot, []).append(exposure)

    summaries = []
    for slot in sorted(by_slot):
        attempts = by_slot[slot]
        first = attempts[0]
        summaries.append(
            BatchSlotSummary(
                sample_slot=slot,
                attempt_count=len(attempts),
                first_target_dose=first.target_dose,
                first_target_time=first.target_time,
                cumulative_actual_dose=sum(
                    exposure.actual_dose for exposure in attempts if exposure.actual_dose is not None
                ),
                cumulative_actual_time=sum(
                    exposure.actual_time for exposure in attempts if exposure.actual_time is not None
                ),
                state=_slot_state(attempts),
                abort_reasons=tuple(
                    exposure.end_reason
                    for exposure in attempts
                    if exposure.state is BatchExposureState.FAILED and exposure.end_reason
                ),
            )
        )
    return tuple(summaries), tuple(unplaced)


def project_batch(dds: DdsLiveSnapshot, history: ExperimentHistorySnapshot) -> BatchProjection:
    selected_name, selection_source = _select_name(dds, history)
    queue_items = dds.queue.value or ()
    if selected_name is None:
        return BatchProjection(
            name=None,
            selection_source=selection_source,
            exposures=(),
            slots=(),
            unplaced_exposures=(),
            total_queue_count=len(queue_items),
            matching_queue_count=0,
            queue_overlap_removed=False,
            history_possibly_truncated=False,
        )

    matching_history_newest_first = []
    for record in history.records:
        if _batch_name(record.name) != selected_name:
            break
        matching_history_newest_first.append(record)

    exposures = [_history_exposure(record) for record in reversed(matching_history_newest_first)]
    experiment = dds.experiment.value
    current_run = experiment.run if experiment is not None else None
    if current_run is not None:
        existing_index = next(
            (index for index, exposure in enumerate(exposures) if exposure.uuid == current_run.uuid),
            None,
        )
        existing = exposures[existing_index] if existing_index is not None else None
        current = _current_exposure(dds, existing)
        if current is not None:
            if existing_index is None:
                exposures.append(current)
            else:
                exposures[existing_index] = current

    matching_queue = []
    for item in queue_items:
        if item.settings is None or _batch_name(item.settings.name) != selected_name:
            break
        matching_queue.append(item)

    overlap_removed = False
    if current_run is not None and experiment.phase in _PRE_RUNNING_PHASES and matching_queue:
        first_settings = matching_queue[0].settings
        if first_settings is not None and _settings_key(first_settings) == _settings_key(current_run.settings):
            matching_queue = matching_queue[1:]
            overlap_removed = True

    exposures.extend(
        _queue_exposure(item.position, item.settings)
        for item in matching_queue
        if item.settings is not None
    )
    exposure_tuple = tuple(exposures)
    slots, unplaced = _summarize_slots(exposure_tuple)
    history_truncated = (
        history.possibly_truncated
        and len(matching_history_newest_first) == len(history.records)
        and bool(history.records)
    )
    return BatchProjection(
        name=selected_name,
        selection_source=selection_source,
        exposures=exposure_tuple,
        slots=slots,
        unplaced_exposures=unplaced,
        total_queue_count=len(queue_items),
        matching_queue_count=len(matching_queue),
        queue_overlap_removed=overlap_removed,
        history_possibly_truncated=history_truncated,
    )
