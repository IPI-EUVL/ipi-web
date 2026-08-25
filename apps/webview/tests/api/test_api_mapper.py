from __future__ import annotations

import uuid
from dataclasses import replace

from chamber_ctl.subsystems import uuids
from ipi_webview.api.mapper import PublicSnapshotMapper
from ipi_webview.api.models import HealthState, ProgressMode, PublicExperimentPhase
from ipi_webview.api.settings import ApiSettings
from ipi_webview.batch.models import (
    BatchExposure,
    BatchExposureState,
    BatchProjection,
    BatchSelectionSource,
    BatchSlotSummary,
    ExperimentHistorySnapshot,
    LiveBatchSnapshot,
)
from ipi_webview.dds.models import (
    BatchControllerAttempt,
    BatchControllerPlanEntry,
    BatchControllerState,
    DdsLiveSnapshot,
    ExperimentPhase,
    ExperimentReason,
    ExperimentRun,
    ExperimentState,
    ExposureSettingsData,
    ObservedValue,
    StageState,
    StatusSeverity,
    SubsystemStatus,
    SubsystemStatusItem,
)


def _snapshot() -> LiveBatchSnapshot:
    run_id = uuid.uuid4()
    settings = ExposureSettingsData(
        "Batch A", "Description", 0.0, 10.0, "Operator", "ZR-1", 2, "resist", 1.0, 2.0, 3.0
    )
    experiment = ExperimentState(
        ExperimentPhase.RUNNING,
        ExperimentRun(run_id, "exposure", "Batch A", "Description", settings),
    )
    observed = 98.0
    subsystems = (
        SubsystemStatus(
            uuids.UUID_EXPOSURE_CONTROLLER,
            "Exposure Controller",
            True,
            (
                SubsystemStatusItem(StatusSeverity.INFO, 0, "Running"),
                SubsystemStatusItem(StatusSeverity.WARNING, 11, "Minor issue"),
                SubsystemStatusItem(StatusSeverity.ALARM, 12, "Major issue"),
            ),
        ),
        SubsystemStatus(
            uuids.UUID_DEVELOPMENT_METRICS_CONTROLLER,
            "Development Metrics Controller",
            False,
            (),
        ),
    )
    dds = DdsLiveSnapshot(
        revision=8,
        emitted_at=99.0,
        transport_ready=ObservedValue(True, observed, observed, None),
        experiment=ObservedValue(experiment, observed, observed, None),
        experiment_reasons=ObservedValue(
            (ExperimentReason("Laser Controller", "Ongoing", "Warming"),), observed, observed, None
        ),
        current_dose=ObservedValue(5.0, observed, observed, None),
        current_time=ObservedValue(7.0, observed, observed, None),
        queue=ObservedValue((), observed, observed, None),
        stage_position=ObservedValue((1.5, 25.0), observed, observed, None),
        stage_state=ObservedValue(StageState.MOVING, observed, observed, None),
        current_slot=ObservedValue(2, observed, observed, None),
        subsystems=ObservedValue(subsystems, observed, observed, None),
    )
    exposure = BatchExposure(
        run_id,
        None,
        90.0,
        "Batch A",
        2,
        10.0,
        0.0,
        5.0,
        7.0,
        BatchExposureState.CURRENT,
        None,
        None,
    )
    batch = BatchProjection(
        "Batch A",
        BatchSelectionSource.CURRENT_RUN,
        (exposure,),
        (BatchSlotSummary(2, 1, 10.0, 0.0, 5.0, 7.0, BatchExposureState.CURRENT, ()),),
        (),
        1,
        0,
        True,
        False,
    )
    history = ExperimentHistorySnapshot(2, 99.0, (), observed, observed, None, 50, False)
    return LiveBatchSnapshot(5, 99.0, dds, history, batch)


def test_public_mapper_sanitizes_subsystems_and_maps_live_batch() -> None:
    mapper = PublicSnapshotMapper(
        frozenset({uuids.UUID_EXPOSURE_CONTROLLER}),
        wall_clock=lambda: 100.0,
    )

    result = mapper.map(_snapshot())
    payload = result.model_dump(mode="json")

    assert result.experiment.phase is PublicExperimentPhase.EXPOSING
    assert result.experiment.details is not None
    assert result.experiment.details.sample_number == 3
    assert result.experiment.reasons[0].reason == "Warming"
    assert result.progress.mode is ProgressMode.DOSE
    assert result.progress.percent == 50.0
    assert result.queue.remaining_count == 0
    assert result.batch.slots[0].sample_number == 3
    assert result.batch.exposures[0].sample_number == 3
    assert result.stage.current_sample_number == 3
    assert result.stage.position is not None
    assert result.stage.position.theta == 1.5
    assert result.subsystems[0].primary_status == "Running"
    assert result.subsystems[1].critical is False
    assert "uuid" not in payload["subsystems"][0]
    assert "code" not in payload["subsystems"][0]["issues"][0]


def test_public_mapper_prefers_authoritative_batch_controller_state() -> None:
    snapshot = _snapshot()
    batch_uuid = uuid.uuid4()
    run_uuid = uuid.uuid4()
    controller_state = BatchControllerState(
        emitted_at=99.0,
        phase="waiting_continue",
        message="Manual mode is ready.",
        last_error=None,
        lease_owned=True,
        active_batch_uuid=batch_uuid,
        name="Authoritative curve",
        description="Controller-owned",
        revision=3,
        manifest_status="active",
        mode="manual",
        paused=False,
        cancel_pending=False,
        decision_kind="start_remainder",
        decision_message="Continue required",
        plan_entries=(
            BatchControllerPlanEntry(1, 4, "dose", 20.0, "under_target", 5.0, 2.0, 1, 15.0, 0.0),
                BatchControllerPlanEntry(2, 5, "dose", 10.0, "overshot", 12.0, 2.0, 1, 0.0, 2.0),
        ),
        attempts=(
            BatchControllerAttempt(run_uuid, 4, 90.0, 91.0, "STOPPED", "short", 5.0, 2.0, 1, None),
                BatchControllerAttempt(uuid.uuid4(), 5, 92.0, 93.0, "STOPPED", "target exceeded", 12.0, 2.0, 1, None),
        ),
    )
    snapshot = replace(
        snapshot,
        dds=replace(
            snapshot.dds,
            batch_controller=ObservedValue(controller_state, 99.0, 99.0, None),
        ),
    )

    result = PublicSnapshotMapper(frozenset(), wall_clock=lambda: 100.0).map(snapshot)

    assert result.batch.authoritative is True
    assert result.batch.selection_source == "controller"
    assert result.batch.batch_id == batch_uuid
    assert result.batch.name == "Authoritative curve"
    assert result.batch.execution_mode == "manual"
    assert result.batch.controller_phase == "waiting_continue"
    assert result.batch.lease_owned is True
    assert result.batch.plan_entries[0].sample_number == 5
    assert result.batch.plan_entries[0].cumulative_actual == 5.0
    assert result.batch.exposures[0].run_id == run_uuid
    assert result.batch.exposures[0].state == "stopped"
    assert result.batch.plan_entries[1].state == "overshot"
    assert result.batch.slots[1].state == "overshot"
    assert result.batch.exposures[1].state == "overshot"


def test_authoritative_batch_marks_unmeasured_work_unavailable_and_uses_live_active_dose() -> None:
    snapshot = _snapshot()
    batch_uuid = uuid.uuid4()
    run_uuid = snapshot.dds.experiment.value.run.uuid
    controller_state = BatchControllerState(
        emitted_at=99.0,
        phase="wait_active",
        message="Batch run is still active.",
        last_error=None,
        lease_owned=True,
        active_batch_uuid=batch_uuid,
        name="Live curve",
        description="",
        revision=1,
        manifest_status="active",
        mode="automatic",
        paused=False,
        cancel_pending=False,
        decision_kind="wait_active",
        decision_message="Batch run is still active.",
        plan_entries=(
            BatchControllerPlanEntry(1, 2, "dose", 10.0, "under_target", 0.0, 0.0, 1, 10.0, 0.0),
            BatchControllerPlanEntry(2, 3, "dose", 20.0, "under_target", 0.0, 0.0, 0, 20.0, 0.0),
        ),
        attempts=(
            BatchControllerAttempt(run_uuid, 2, 98.0, None, None, None, None, None, 0, None),
        ),
    )
    snapshot = replace(
        snapshot,
        dds=replace(
            snapshot.dds,
            batch_controller=ObservedValue(controller_state, 99.0, 99.0, None),
        ),
    )

    result = PublicSnapshotMapper(frozenset(), wall_clock=lambda: 100.0).map(snapshot)

    assert result.batch.plan_entries[0].cumulative_actual == 5.0
    assert result.batch.plan_entries[1].cumulative_actual is None
    assert result.batch.exposures[0].actual_dose == 5.0


def test_authoritative_batch_keeps_completed_sample_actuals_while_next_sample_is_active() -> None:
    snapshot = _snapshot()
    run_uuid = snapshot.dds.experiment.value.run.uuid
    controller_state = BatchControllerState(
        emitted_at=99.0,
        phase="wait_active",
        message="Batch run is still active.",
        last_error=None,
        lease_owned=True,
        active_batch_uuid=uuid.uuid4(),
        name="Live curve",
        description="",
        revision=1,
        manifest_status="active",
        mode="automatic",
        paused=False,
        cancel_pending=False,
        decision_kind="wait_active",
        decision_message="Batch run is still active.",
        plan_entries=(
            BatchControllerPlanEntry(1, 0, "dose", 5.0, "within_tolerance", 5.0, 2.0, 1, 0.0, 0.0),
            BatchControllerPlanEntry(2, 2, "dose", 10.0, "under_target", 0.0, 0.0, 0, 10.0, 0.0),
            BatchControllerPlanEntry(3, 3, "dose", 20.0, "under_target", 0.0, 0.0, 0, 20.0, 0.0),
        ),
        attempts=(
            BatchControllerAttempt(uuid.uuid4(), 0, 90.0, 91.0, "STOPPED", "done", 5.0, 2.0, 1, None),
            BatchControllerAttempt(run_uuid, 2, 98.0, None, None, None, None, None, 0, None),
        ),
    )
    snapshot = replace(
        snapshot,
        dds=replace(
            snapshot.dds,
            batch_controller=ObservedValue(controller_state, 99.0, 99.0, None),
        ),
    )

    result = PublicSnapshotMapper(frozenset(), wall_clock=lambda: 100.0).map(snapshot)

    assert [entry.cumulative_actual for entry in result.batch.plan_entries] == [5.0, 5.0, None]
    assert result.batch.plan_entries[0].state == "within_tolerance"

    failed = replace(
        snapshot,
        dds=replace(
            snapshot.dds,
            batch_controller=ObservedValue(controller_state, 99.0, 100.0, "DDS read failed"),
        ),
    )
    stale = replace(
        snapshot,
        dds=replace(
            snapshot.dds,
            batch_controller=ObservedValue(controller_state, 80.0, 80.0, None),
        ),
    )

    assert PublicSnapshotMapper(frozenset(), wall_clock=lambda: 100.0).map(failed).batch.authoritative is True
    assert PublicSnapshotMapper(frozenset(), wall_clock=lambda: 100.0).map(stale).batch.authoritative is False


def test_critical_issues_are_all_preserved_and_noncritical_disconnect_does_not_add_one() -> None:
    mapper = PublicSnapshotMapper(
        frozenset({uuids.UUID_EXPOSURE_CONTROLLER}),
        wall_clock=lambda: 100.0,
    )

    result = mapper.map(_snapshot())

    assert result.system.state is HealthState.ERROR
    assert result.system.label == "Errors reported"
    assert [(issue.severity.value, issue.source, issue.message) for issue in result.system.issues] == [
        ("error", "Exposure Controller", "Major issue"),
        ("warning", "Exposure Controller", "Minor issue"),
    ]


def test_api_settings_resolve_friendly_critical_aliases_and_uuid() -> None:
    extra_uuid = uuid.uuid4()
    settings = ApiSettings(
        critical_subsystems=f"exposure, queue, {extra_uuid}",
        _env_file=None,
    )

    assert settings.critical_subsystem_uuids == frozenset(
        {uuids.UUID_EXPOSURE_CONTROLLER, uuids.UUID_EXPERIMENT_QUEUE_CONTROLLER, extra_uuid}
    )


def test_history_degradation_does_not_change_hardware_system_health() -> None:
    snapshot = _snapshot()
    snapshot = LiveBatchSnapshot(
        revision=snapshot.revision,
        emitted_at=snapshot.emitted_at,
        dds=snapshot.dds,
        history=ExperimentHistorySnapshot(
            revision=3,
            emitted_at=100.0,
            records=(),
            observed_at=98.0,
            attempted_at=100.0,
            error="OSError: dataset unavailable",
            query_limit=50,
            possibly_truncated=False,
        ),
        batch=snapshot.batch,
    )
    mapper = PublicSnapshotMapper(frozenset(), wall_clock=lambda: 100.0)

    result = mapper.map(snapshot)

    assert result.sources["history"].state.value == "degraded"
    assert result.system.state is HealthState.OK


def test_stage_source_recovers_from_fresh_position_and_slot_after_stale_state() -> None:
    snapshot = _snapshot()
    dds = replace(
        snapshot.dds,
        stage_state=ObservedValue(StageState.IDLE, 80.0, 80.0, None),
        stage_position=ObservedValue((1.5, 25.0), 99.0, 99.0, None),
        current_slot=ObservedValue(2, 99.0, 99.0, None),
    )
    mapper = PublicSnapshotMapper(frozenset(), wall_clock=lambda: 100.0)

    result = mapper.map(replace(snapshot, dds=dds))

    assert result.sources["stage"].state.value == "available"
    assert result.sources["stage"].observed_at == 99.0


def test_idle_dose_and_time_are_not_applicable_when_oscilloscope_is_connected() -> None:
    snapshot = _snapshot()
    oscilloscope = SubsystemStatus(
        uuids.UUID_OSCILLOSCOPE_CONTROLLER,
        "Oscilloscope Controller",
        True,
        (SubsystemStatusItem(StatusSeverity.INFO, 0, "Idle"),),
    )
    dds = replace(
        snapshot.dds,
        experiment=ObservedValue(ExperimentState(ExperimentPhase.STOPPED, None), 99.0, 99.0, None),
        current_dose=ObservedValue(attempted_at=99.0),
        current_time=ObservedValue(attempted_at=99.0),
        subsystems=ObservedValue((*snapshot.dds.subsystems.value, oscilloscope), 99.0, 99.0, None),
    )
    mapper = PublicSnapshotMapper(frozenset(), wall_clock=lambda: 100.0)

    result = mapper.map(replace(snapshot, dds=dds))

    assert result.sources["dose"].state.value == "not_applicable"
    assert result.sources["time"].state.value == "not_applicable"


def test_stopped_required_subsystem_does_not_report_a_dds_server_failure() -> None:
    snapshot = _snapshot()
    disconnected_queue = SubsystemStatus(
        uuids.UUID_EXPERIMENT_QUEUE_CONTROLLER,
        "Exposure Queue Controller",
        False,
        (),
    )
    dds = replace(
        snapshot.dds,
        queue=ObservedValue((), 98.0, 100.0, "Subsystem unavailable"),
        subsystems=ObservedValue((*snapshot.dds.subsystems.value, disconnected_queue), 100.0, 100.0, None),
    )
    mapper = PublicSnapshotMapper(
        frozenset({uuids.UUID_EXPERIMENT_QUEUE_CONTROLLER}),
        wall_clock=lambda: 100.0,
    )

    result = mapper.map(replace(snapshot, dds=dds))

    assert result.sources["transport"].state.value == "available"
    assert all(issue.source != "DDS server" for issue in result.system.issues)
    assert any(issue.source == "Exposure Queue Controller" for issue in result.system.issues)