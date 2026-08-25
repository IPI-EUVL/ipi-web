from __future__ import annotations

import time
import uuid

from ipi_webview.dds.adapter import EcsLiveAdapter, EcsLiveAdapterConfig
from ipi_webview.dds.events import DataSource, TransportEvent
from ipi_webview.dds.models import (
    ExperimentPhase,
    ExperimentRun,
    ExperimentState,
    ExposureSettingsData,
    QueueItem,
    StageState,
    StatusSeverity,
    SubsystemStatus,
    SubsystemStatusItem,
)


def _settings(name: str = "Batch A") -> ExposureSettingsData:
    return ExposureSettingsData(
        name=name,
        description="Description",
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


def _experiment(run_uuid: uuid.UUID) -> ExperimentState:
    return ExperimentState(
        phase=ExperimentPhase.RUNNING,
        run=ExperimentRun(run_uuid, "exposure", "Batch A", "Description", _settings()),
    )


class FakeTransport:
    def __init__(self, sink) -> None:
        self.sink = sink
        self.queue_polls = 0
        self.slot_polls = 0
        self.subsystem_polls = 0
        self.closed = False

    def start(self) -> None:
        self.emit(DataSource.TRANSPORT, True)

    def emit(
        self,
        source: DataSource,
        value=None,
        *,
        error: str | None = None,
        received_at: float | None = None,
        sampled_at: float | None = None,
    ) -> None:
        received_at = time.time() if received_at is None else received_at
        sampled_at = received_at if sampled_at is None else sampled_at
        self.sink(TransportEvent(source, received_at, sampled_at, value=value, error=error))

    def poll_queue(self) -> None:
        self.queue_polls += 1

    def poll_current_slot(self) -> None:
        self.slot_polls += 1

    def poll_subsystems(self) -> None:
        self.subsystem_polls += 1

    def close(self) -> None:
        self.closed = True


def _started_adapter():
    transports = []

    def factory(_config, sink):
        transport = FakeTransport(sink)
        transports.append(transport)
        return transport

    adapter = EcsLiveAdapter(
        EcsLiveAdapterConfig(
            queue_poll_interval=60.0,
            current_slot_poll_interval=60.0,
            subsystem_poll_interval=60.0,
            publish_interval=0.01,
        ),
        transport_factory=factory,
    )
    adapter.start()
    adapter.get_update(timeout=1.0)
    deadline = time.time() + 1.0
    while not transports and time.time() < deadline:
        time.sleep(0.001)
    assert transports
    return adapter, transports[0]


def _next_matching(adapter: EcsLiveAdapter, predicate, timeout: float = 1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        snapshot = adapter.get_update(timeout=max(0.001, deadline - time.time()))
        if predicate(snapshot):
            return snapshot
    raise AssertionError("No matching adapter snapshot was emitted.")


def test_run_transition_resets_progress_and_rejects_older_sample() -> None:
    adapter, transport = _started_adapter()
    try:
        transport.emit(DataSource.CURRENT_DOSE, 9.0, received_at=10.0, sampled_at=10.0)
        transport.emit(DataSource.CURRENT_TIME, 8.0, received_at=10.0, sampled_at=10.0)
        transport.emit(DataSource.EXPERIMENT, _experiment(uuid.uuid4()), received_at=20.0, sampled_at=20.0)

        reset = _next_matching(adapter, lambda snapshot: snapshot.experiment.value is not None)
        assert reset.current_dose.value is None
        assert reset.current_time.value is None

        transport.emit(DataSource.CURRENT_DOSE, 99.0, received_at=21.0, sampled_at=19.0)
        transport.emit(DataSource.CURRENT_DOSE, 1.25, received_at=22.0, sampled_at=21.0)

        current = _next_matching(adapter, lambda snapshot: snapshot.current_dose.value == 1.25)
        assert current.current_dose.observed_at == 22.0
    finally:
        adapter.close()


def test_failed_poll_retains_last_queue_and_records_error() -> None:
    adapter, transport = _started_adapter()
    try:
        queue_value = (QueueItem(position=0, settings=_settings()),)
        transport.emit(DataSource.QUEUE, queue_value)
        _next_matching(adapter, lambda snapshot: snapshot.queue.value == queue_value)

        transport.emit(DataSource.QUEUE, error="Queue subsystem unavailable")
        failed = _next_matching(adapter, lambda snapshot: snapshot.queue.error is not None)

        assert failed.queue.value == queue_value
        assert failed.queue.error == "Queue subsystem unavailable"
        assert failed.queue.observed_at is not None
        assert failed.queue.attempted_at is not None
        assert failed.transport_ready.value is True
        assert failed.transport_ready.error is None

        transport.emit(DataSource.QUEUE, queue_value)
        recovered = _next_matching(adapter, lambda snapshot: snapshot.queue.error is None)
        assert recovered.transport_ready.value is True
        assert recovered.transport_ready.error is None
    finally:
        adapter.close()


def test_failed_subsystem_poll_retains_last_confirmed_status() -> None:
    adapter, transport = _started_adapter()
    subsystem_uuid = uuid.uuid4()
    statuses = (
        SubsystemStatus(
            subsystem_uuid,
            "Oscilloscope Controller",
            True,
            (SubsystemStatusItem(StatusSeverity.WARNING, 100, "Laser off"),),
        ),
    )
    try:
        transport.emit(DataSource.SUBSYSTEMS, statuses, received_at=10.0)
        confirmed = _next_matching(adapter, lambda snapshot: snapshot.subsystems.value == statuses)
        assert confirmed.subsystems.error is None

        transport.emit(DataSource.SUBSYSTEMS, error="Status read timed out", received_at=11.0)
        degraded = _next_matching(adapter, lambda snapshot: snapshot.subsystems.error is not None)

        assert degraded.subsystems.value == statuses
        assert degraded.subsystems.observed_at == 10.0
        assert degraded.subsystems.attempted_at == 11.0
        assert degraded.subsystems.error == "Status read timed out"
    finally:
        adapter.close()


def test_latest_stage_update_wins_in_bounded_output_queue() -> None:
    adapter, transport = _started_adapter()
    try:
        for index in range(20):
            transport.emit(DataSource.STAGE_POSITION, (float(index), float(index + 1)))
        transport.emit(DataSource.STAGE_STATE, StageState.MOVING)
        transport.emit(DataSource.CURRENT_SLOT, -1)

        latest = _next_matching(
            adapter,
            lambda snapshot: snapshot.stage_position.value == (19.0, 20.0) and snapshot.current_slot.value == -1,
        )
        assert latest.stage_state.value is StageState.MOVING
        assert latest.revision < 20
    finally:
        adapter.close()
        assert transport.closed
