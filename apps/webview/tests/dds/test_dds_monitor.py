from __future__ import annotations

import io
import json
import uuid

from ipi_webview.dds.models import (
    DdsLiveSnapshot,
    ExperimentPhase,
    ExperimentRun,
    ExperimentState,
    ExposureSettingsData,
    ObservedValue,
    StageState,
)
from ipi_webview.dds_monitor import print_updates, to_json_value


def _snapshot() -> DdsLiveSnapshot:
    run_uuid = uuid.UUID("c51813e6-5c3e-49b7-b18d-9868d4b63670")
    settings = ExposureSettingsData(
        name="Batch A",
        description="Test exposure",
        target_time=0.0,
        target_dose=5.0,
        operator="Operator",
        zr_filter="ZR-1",
        sample_slot=2,
        sample_type="resist",
        base_pressure=1.0,
        operating_pressure=2.0,
        flow_sccm=3.0,
    )
    experiment = ExperimentState(
        ExperimentPhase.RUNNING,
        ExperimentRun(run_uuid, "exposure", "Batch A", "Test exposure", settings),
    )
    empty = ObservedValue()
    return DdsLiveSnapshot(
        revision=4,
        emitted_at=100.0,
        transport_ready=ObservedValue(True, 99.0, 99.0, None),
        experiment=ObservedValue(experiment, 99.0, 99.0, None),
        experiment_reasons=empty,
        current_dose=ObservedValue(1.25, 100.0, 100.0, None),
        current_time=ObservedValue(2.5, 100.0, 100.0, None),
        queue=empty,
        stage_position=ObservedValue((1.0, 2.0), 100.0, 100.0, None),
        stage_state=ObservedValue(StageState.MOVING, 100.0, 100.0, None),
        current_slot=ObservedValue(-1, 100.0, 100.0, None),
        subsystems=empty,
    )


class FakeAdapter:
    def __init__(self, snapshot: DdsLiveSnapshot) -> None:
        self.snapshot = snapshot
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def get_update(self, timeout=None) -> DdsLiveSnapshot:
        assert timeout == 1.0
        return self.snapshot

    def close(self) -> None:
        self.closed = True


def test_to_json_value_serializes_nested_uuid_enums_and_tuples() -> None:
    serialized = to_json_value(_snapshot())

    assert serialized["experiment"]["value"]["phase"] == "RUNNING"
    assert serialized["experiment"]["value"]["run"]["uuid"] == "c51813e6-5c3e-49b7-b18d-9868d4b63670"
    assert serialized["stage_state"]["value"] == "MOVING"
    assert serialized["stage_position"]["value"] == [1.0, 2.0]
    assert serialized["current_slot"]["value"] == -1


def test_print_updates_prints_json_and_closes_adapter() -> None:
    adapter = FakeAdapter(_snapshot())
    output = io.StringIO()

    result = print_updates(adapter, output=output, compact=True, max_updates=1)

    assert result == 0
    assert adapter.started is True
    assert adapter.closed is True
    assert json.loads(output.getvalue())["revision"] == 4


def test_print_updates_can_skip_startup_snapshots() -> None:
    startup = _snapshot()
    current = _snapshot()
    current = type(current)(
        revision=5,
        emitted_at=current.emitted_at,
        transport_ready=current.transport_ready,
        experiment=current.experiment,
        experiment_reasons=current.experiment_reasons,
        current_dose=current.current_dose,
        current_time=current.current_time,
        queue=current.queue,
        stage_position=current.stage_position,
        stage_state=current.stage_state,
        current_slot=current.current_slot,
        subsystems=current.subsystems,
    )

    class SequenceAdapter(FakeAdapter):
        def __init__(self):
            super().__init__(startup)
            self.snapshots = iter((startup, current))

        def get_update(self, timeout=None):
            return next(self.snapshots)

    adapter = SequenceAdapter()
    output = io.StringIO()

    print_updates(
        adapter,
        output=output,
        compact=True,
        max_updates=1,
        accept_update=lambda snapshot: snapshot.revision > 4,
    )

    assert json.loads(output.getvalue())["revision"] == 5
    assert adapter.closed is True


def test_print_updates_can_prepare_a_smaller_output_value() -> None:
    adapter = FakeAdapter(_snapshot())
    output = io.StringIO()

    print_updates(
        adapter,
        output=output,
        compact=True,
        max_updates=1,
        prepare_update=lambda snapshot: {"revision": snapshot.revision},
    )

    assert json.loads(output.getvalue()) == {"revision": 4}