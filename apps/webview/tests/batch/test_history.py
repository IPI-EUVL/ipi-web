from __future__ import annotations

import time
import uuid

from ipi_webview.batch.history import ExperimentHistoryAdapter, ExperimentHistoryConfig


class FakeEntry:
    def __init__(self, name: str, timestamp: float, tags: dict) -> None:
        self.name = name
        self.timestamp = timestamp
        self.tags = tags

    def get_name(self):
        return self.name

    def get_timestamp(self):
        return self.timestamp

    def get_tags(self):
        return self.tags


class FakeLibrary:
    def __init__(self, entries) -> None:
        self.entries = entries
        self.queries = []
        self.closed = False

    def query(self, filters, limit=None):
        self.queries.append((filters, limit))
        return self.entries[:limit]

    def close(self) -> None:
        self.closed = True


def _next_matching(adapter, predicate, timeout: float = 1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        snapshot = adapter.get_update(timeout=max(0.001, deadline - time.time()))
        if predicate(snapshot):
            return snapshot
    raise AssertionError("No matching history snapshot was emitted.")


def test_history_adapter_queries_latest_minimal_exposure_records_and_closes() -> None:
    run_uuid = uuid.uuid4()
    library = FakeLibrary(
        [
            FakeEntry(
                " Batch A ",
                100.0,
                {
                    "experiment": "exposure",
                    "run": run_uuid.hex,
                    "sample": "2",
                    "target_dose": "15.0",
                    "target_time": "0.0",
                    "dose": "5.25",
                    "runtime": "12.5",
                    "status": "ABORTED",
                    "abort_reason": "Stopped by user.",
                },
            )
        ]
    )
    paths = []

    def factory(path):
        paths.append(path)
        return library

    adapter = ExperimentHistoryAdapter(
        ExperimentHistoryConfig(data_path="C:/experiment-data", poll_interval=60.0, query_limit=50),
        library_factory=factory,
    )
    adapter.start()
    snapshot = _next_matching(adapter, lambda candidate: bool(candidate.records))
    adapter.close()

    assert paths == ["C:/experiment-data"]
    assert library.queries == [({"tags": {"experiment": "exposure"}}, 50)]
    assert library.closed is True
    assert snapshot.error is None
    assert snapshot.possibly_truncated is False
    assert snapshot.records[0].uuid == run_uuid
    assert snapshot.records[0].name == " Batch A "
    assert snapshot.records[0].sample_slot == 2
    assert snapshot.records[0].target_dose == 15.0
    assert snapshot.records[0].actual_dose == 5.25
    assert snapshot.records[0].actual_time == 12.5
    assert snapshot.records[0].status == "ABORTED"
    assert snapshot.records[0].end_reason == "Stopped by user."


def test_history_adapter_retains_records_when_refresh_fails() -> None:
    run_uuid = uuid.uuid4()

    class FailingLibrary(FakeLibrary):
        def query(self, filters, limit=None):
            if self.queries:
                raise OSError("Box path unavailable")
            return super().query(filters, limit)

    library = FailingLibrary(
        [FakeEntry("Batch A", 100.0, {"experiment": "exposure", "run": run_uuid.hex})]
    )
    adapter = ExperimentHistoryAdapter(
        ExperimentHistoryConfig(data_path="C:/experiment-data", poll_interval=60.0),
        library_factory=lambda _path: library,
    )
    adapter.start()
    first = _next_matching(adapter, lambda candidate: bool(candidate.records))
    adapter.request_refresh()
    failed = _next_matching(adapter, lambda candidate: candidate.error is not None)
    adapter.close()

    assert first.records[0].uuid == run_uuid
    assert failed.records == first.records
    assert failed.observed_at == first.observed_at
    assert failed.error == "OSError: Box path unavailable"