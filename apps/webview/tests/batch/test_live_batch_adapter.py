from __future__ import annotations

import queue
import time
import uuid

from ipi_webview.batch.adapter import LiveBatchAdapter, LiveBatchAdapterConfig
from ipi_webview.batch.history import ExperimentHistoryConfig
from ipi_webview.batch.models import ExperimentHistorySnapshot
from ipi_webview.dds.adapter import EcsLiveAdapterConfig
from ipi_webview.dds.models import (
    DdsLiveSnapshot,
    ExperimentPhase,
    ExperimentRun,
    ExperimentState,
    ExposureSettingsData,
    ObservedValue,
)


def _settings(name: str = "Batch A") -> ExposureSettingsData:
    return ExposureSettingsData(name, "", 0.0, 5.0, "", "", 0, "", None, None, None)


def _dds(revision: int, run_uuid=None) -> DdsLiveSnapshot:
    run = None if run_uuid is None else ExperimentRun(run_uuid, "exposure", "Batch A", "", _settings())
    phase = ExperimentPhase.STOPPED if run is None else ExperimentPhase.RUNNING
    empty = ObservedValue()
    return DdsLiveSnapshot(
        revision,
        float(revision),
        ObservedValue(True, 1.0, 1.0, None),
        ObservedValue(ExperimentState(phase, run), 1.0, 1.0, None),
        empty,
        empty,
        empty,
        ObservedValue((), 1.0, 1.0, None),
        empty,
        empty,
        empty,
        empty,
    )


def _history() -> ExperimentHistorySnapshot:
    return ExperimentHistorySnapshot(1, 1.0, (), 1.0, 1.0, None, 50, False)


class FakeSource:
    def __init__(self) -> None:
        self.updates = queue.Queue()
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def emit(self, value) -> None:
        self.updates.put(value)

    def get_update(self, timeout=None):
        return self.updates.get(timeout=timeout)

    def close(self, timeout=5.0) -> None:
        self.closed = True


class FakeHistorySource(FakeSource):
    def __init__(self) -> None:
        super().__init__()
        self.refresh_count = 0

    def request_refresh(self) -> None:
        self.refresh_count += 1


def _next_matching(adapter, predicate, timeout: float = 1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        snapshot = adapter.get_update(timeout=max(0.001, deadline - time.time()))
        if predicate(snapshot):
            return snapshot
    raise AssertionError("No matching live batch snapshot was emitted.")


def test_live_batch_adapter_combines_sources_and_refreshes_only_on_uuid_change() -> None:
    dds = FakeSource()
    history = FakeHistorySource()
    adapter = LiveBatchAdapter(
        LiveBatchAdapterConfig(EcsLiveAdapterConfig(), ExperimentHistoryConfig()),
        dds_factory=lambda _config: dds,
        history_factory=lambda _config: history,
    )
    first_uuid = uuid.uuid4()
    second_uuid = uuid.uuid4()
    adapter.start()
    history.emit(_history())
    dds.emit(_dds(1, first_uuid))

    first = _next_matching(adapter, lambda snapshot: snapshot.dds.revision == 1)
    assert first.batch.name == "Batch A"
    assert history.refresh_count == 1

    dds.emit(_dds(2, first_uuid))
    _next_matching(adapter, lambda snapshot: snapshot.dds.revision == 2)
    assert history.refresh_count == 1

    dds.emit(_dds(3, second_uuid))
    _next_matching(adapter, lambda snapshot: snapshot.dds.revision == 3)
    assert history.refresh_count == 2

    dds.emit(_dds(4, None))
    _next_matching(adapter, lambda snapshot: snapshot.dds.revision == 4)
    assert history.refresh_count == 3

    adapter.close()
    assert dds.closed is True
    assert history.closed is True