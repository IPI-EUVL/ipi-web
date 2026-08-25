from __future__ import annotations

import uuid

from ipi_webview.batch.models import (
    BatchExposureState,
    BatchSelectionSource,
    ExperimentHistoryRecord,
    ExperimentHistorySnapshot,
)
from ipi_webview.batch.projector import project_batch
from ipi_webview.dds.models import (
    DdsLiveSnapshot,
    ExperimentPhase,
    ExperimentRun,
    ExperimentState,
    ExposureSettingsData,
    ObservedValue,
    QueueItem,
)


def _settings(
    name: str = "Batch A",
    *,
    slot: int | None = 2,
    target_dose: float | None = 15.0,
    target_time: float | None = 0.0,
) -> ExposureSettingsData:
    return ExposureSettingsData(
        name=name,
        description="Description",
        target_time=target_time,
        target_dose=target_dose,
        operator="Operator",
        zr_filter="ZR-1",
        sample_slot=slot,
        sample_type="resist",
        base_pressure=1.0,
        operating_pressure=2.0,
        flow_sccm=3.0,
    )


def _record(
    name: str,
    created_at: float,
    *,
    run_uuid=None,
    slot: int | None = 2,
    target_dose: float | None = 15.0,
    target_time: float | None = 0.0,
    actual_dose: float | None = None,
    actual_time: float | None = None,
    status: str | None = None,
    reason: str | None = None,
) -> ExperimentHistoryRecord:
    return ExperimentHistoryRecord(
        uuid=run_uuid or uuid.uuid4(),
        created_at=created_at,
        name=name,
        sample_slot=slot,
        target_dose=target_dose,
        target_time=target_time,
        actual_dose=actual_dose,
        actual_time=actual_time,
        status=status,
        end_reason=reason,
    )


def _history(*records, truncated: bool = False) -> ExperimentHistorySnapshot:
    return ExperimentHistorySnapshot(1, 100.0, tuple(records), 100.0, 100.0, None, 50, truncated)


def _dds(
    *,
    phase: ExperimentPhase = ExperimentPhase.STOPPED,
    run_uuid=None,
    run_settings: ExposureSettingsData | None = None,
    queue=(),
    dose: float | None = None,
    runtime: float | None = None,
) -> DdsLiveSnapshot:
    run = None
    if run_uuid is not None:
        settings = run_settings or _settings()
        run = ExperimentRun(run_uuid, "exposure", settings.name, settings.description, settings)
    experiment = ExperimentState(phase, run)
    empty = ObservedValue()
    return DdsLiveSnapshot(
        revision=1,
        emitted_at=100.0,
        transport_ready=ObservedValue(True, 100.0, 100.0, None),
        experiment=ObservedValue(experiment, 100.0, 100.0, None),
        experiment_reasons=empty,
        current_dose=ObservedValue(dose, 100.0, 100.0, None),
        current_time=ObservedValue(runtime, 100.0, 100.0, None),
        queue=ObservedValue(tuple(queue), 100.0, 100.0, None),
        stage_position=empty,
        stage_state=empty,
        current_slot=empty,
        subsystems=empty,
    )


def test_current_batch_stops_at_interruption_and_deduplicates_preinit_queue_head() -> None:
    current_uuid = uuid.uuid4()
    current_settings = _settings(" Batch A ", slot=3)
    history = _history(
        _record("Batch A", 40.0, run_uuid=current_uuid),
        _record(" Batch A ", 30.0, status="STOPPED", actual_dose=15.1),
        _record("Interrupt", 20.0, status="STOPPED"),
        _record("Batch A", 10.0, status="STOPPED"),
    )
    queue = (
        QueueItem(0, current_settings),
        QueueItem(1, _settings("Batch A", slot=4)),
        QueueItem(2, _settings("Other", slot=5)),
    )

    batch = project_batch(
        _dds(
            phase=ExperimentPhase.PREPARING,
            run_uuid=current_uuid,
            run_settings=current_settings,
            queue=queue,
            dose=2.5,
            runtime=8.0,
        ),
        history,
    )

    assert batch.name == "Batch A"
    assert batch.selection_source is BatchSelectionSource.CURRENT_RUN
    assert batch.queue_overlap_removed is True
    assert batch.matching_queue_count == 1
    assert [exposure.state for exposure in batch.exposures] == [
        BatchExposureState.SUCCEEDED,
        BatchExposureState.CURRENT,
        BatchExposureState.QUEUED,
    ]
    assert [exposure.created_at for exposure in batch.exposures[:2]] == [30.0, 40.0]
    assert batch.exposures[1].actual_dose == 2.5
    assert all(exposure.created_at != 10.0 for exposure in batch.exposures)


def test_running_phase_does_not_remove_identical_queue_head() -> None:
    current_uuid = uuid.uuid4()
    settings = _settings()
    batch = project_batch(
        _dds(
            phase=ExperimentPhase.RUNNING,
            run_uuid=current_uuid,
            run_settings=settings,
            queue=(QueueItem(0, settings),),
        ),
        _history(_record("Batch A", 10.0, run_uuid=current_uuid)),
    )

    assert batch.queue_overlap_removed is False
    assert [exposure.state for exposure in batch.exposures] == [
        BatchExposureState.CURRENT,
        BatchExposureState.QUEUED,
    ]


def test_no_run_uses_queue_head_then_falls_back_to_latest_history() -> None:
    history = _history(
        _record("Last Batch", 20.0, status="STOPPED"),
        _record("Earlier", 10.0, status="STOPPED"),
    )
    queued = project_batch(
        _dds(queue=(QueueItem(0, _settings("Next Batch")), QueueItem(1, _settings("Other")))),
        history,
    )
    retained = project_batch(_dds(), history)

    assert queued.name == "Next Batch"
    assert queued.selection_source is BatchSelectionSource.QUEUE
    assert [exposure.state for exposure in queued.exposures] == [BatchExposureState.QUEUED]
    assert retained.name == "Last Batch"
    assert retained.selection_source is BatchSelectionSource.HISTORY
    assert [exposure.state for exposure in retained.exposures] == [BatchExposureState.SUCCEEDED]


def test_corrective_runs_keep_first_target_and_sum_both_actual_metrics() -> None:
    corrective = _record(
        "Batch A",
        20.0,
        target_dose=10.0,
        target_time=20.0,
        actual_dose=10.0,
        actual_time=22.0,
        status="STOPPED",
        reason="Stopped by user.",
    )
    original = _record(
        "Batch A",
        10.0,
        target_dose=15.0,
        target_time=0.0,
        actual_dose=5.0,
        actual_time=11.0,
        status="ABORTED",
        reason="Laser fault",
    )

    batch = project_batch(_dds(), _history(corrective, original))
    slot = batch.slots[0]

    assert [exposure.created_at for exposure in batch.exposures] == [10.0, 20.0]
    assert batch.exposures[1].state is BatchExposureState.SUCCEEDED
    assert batch.exposures[1].end_reason == "Stopped by user."
    assert slot.attempt_count == 2
    assert slot.first_target_dose == 15.0
    assert slot.first_target_time == 0.0
    assert slot.cumulative_actual_dose == 15.0
    assert slot.cumulative_actual_time == 33.0
    assert slot.state is BatchExposureState.SUCCEEDED
    assert slot.abort_reasons == ("Laser fault",)


def test_all_user_stopped_exposures_that_miss_their_active_target_are_failed() -> None:
    dose_missed = _record(
        "Batch A",
        30.0,
        slot=1,
        target_dose=10.0,
        target_time=100.0,
        actual_dose=9.5,
        actual_time=100.0,
        status="STOPPED",
        reason="Stopped by user.",
    )
    time_missed = _record(
        "Batch A",
        20.0,
        slot=2,
        target_dose=0.0,
        target_time=15.0,
        actual_dose=2.0,
        actual_time=14.0,
        status="STOPPED",
        reason="Stopped by user",
    )
    target_reached = _record(
        "Batch A",
        10.0,
        slot=3,
        target_dose=10.0,
        actual_dose=10.0,
        status="STOPPED",
        reason="Stopped by user.",
    )

    batch = project_batch(_dds(), _history(dose_missed, time_missed, target_reached))

    states_by_slot = {exposure.sample_slot: exposure.state for exposure in batch.exposures}
    assert states_by_slot == {
        1: BatchExposureState.FAILED,
        2: BatchExposureState.FAILED,
        3: BatchExposureState.SUCCEEDED,
    }


def test_history_is_only_flagged_truncated_when_batch_reaches_query_boundary() -> None:
    all_same = project_batch(
        _dds(),
        _history(*(_record("Batch A", float(index)) for index in range(50, 0, -1)), truncated=True),
    )
    interrupted = project_batch(
        _dds(),
        _history(_record("Batch A", 3.0), _record("Other", 2.0), truncated=True),
    )

    assert all_same.history_possibly_truncated is True
    assert interrupted.history_possibly_truncated is False