from __future__ import annotations

import asyncio

from ipi_webview.api.models import (
    BatchSummary,
    ExperimentSummary,
    HealthState,
    LiveResponse,
    ProgressMode,
    ProgressSummary,
    PublicExperimentPhase,
    PublicStageState,
    QueueSummary,
    SourceState,
    SourceSummary,
    StageSummary,
    SystemSummary,
)
from ipi_webview.api.store import SnapshotStore
from ipi_webview.api.app import _parse_last_event_id, sse_stream


class FakeRequest:
    def __init__(self, disconnect_after: int = 100) -> None:
        self.calls = 0
        self.disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self.calls += 1
        return self.calls > self.disconnect_after


def _response(
    revision: int,
    *,
    queue_count: int = 0,
    generated_at: float | None = None,
    subsystem_observed_at: float | None = None,
) -> LiveResponse:
    return LiveResponse(
        revision=revision,
        generated_at=float(revision) if generated_at is None else generated_at,
        system=SystemSummary(state=HealthState.OK, label="System OK", issues=()),
        experiment=ExperimentSummary(phase=PublicExperimentPhase.IDLE, details=None, reasons=()),
        progress=ProgressSummary(mode=ProgressMode.NONE, current=None, target=None, unit=None, percent=None),
        queue=QueueSummary(remaining_count=queue_count, current_batch_remaining_count=queue_count),
        batch=BatchSummary(
            name=None,
            selection_source="none",
            exposures=(),
            slots=(),
            unplaced_exposures=(),
            remaining_count=queue_count,
            possibly_truncated=False,
        ),
        stage=StageSummary(state=PublicStageState.UNKNOWN, current_sample_number=None, position=None),
        subsystems=(),
        sources={} if subsystem_observed_at is None else {
            "subsystems": SourceSummary(
                state=SourceState.AVAILABLE,
                observed_at=subsystem_observed_at,
                attempted_at=subsystem_observed_at,
                error=None,
            )
        },
    )


def test_store_deduplicates_timestamp_only_changes_and_replays_from_event_id() -> None:
    async def scenario() -> None:
        store = SnapshotStore(event_buffer_size=2)
        first = await store.publish(_response(1, generated_at=1.0))
        duplicate = await store.publish(_response(2, generated_at=2.0))
        second = await store.publish(_response(3, queue_count=1))
        third = await store.publish(_response(4, queue_count=2))

        assert first is not None and first.id == 1
        assert duplicate is None
        assert second is not None and second.id == 2
        assert third is not None and third.id == 3
        assert (await store.latest()).revision == 4
        assert [event.id for event in await store.replay(1)] == [2, 3]
        assert [event.id for event in await store.replay(0)] == [3]
        assert [event.id for event in await store.replay(99)] == [3]
        assert [event.id for event in await store.replay(None)] == [3]
        assert "event: live" in third.to_sse()
        assert "id: 3" in third.to_sse()

    asyncio.run(scenario())


def test_store_wait_times_out_without_new_semantic_event() -> None:
    async def scenario() -> None:
        store = SnapshotStore()
        event = await store.publish(_response(1))
        assert event is not None
        assert await store.wait_for_events(event.id, timeout=0.01) == ()

    asyncio.run(scenario())


def test_store_publishes_successful_subsystem_observation_refreshes() -> None:
    async def scenario() -> None:
        store = SnapshotStore()
        first = await store.publish(_response(1, subsystem_observed_at=10.0))
        refreshed = await store.publish(_response(2, subsystem_observed_at=11.5))

        assert first is not None and first.id == 1
        assert refreshed is not None and refreshed.id == 2

    asyncio.run(scenario())


def test_sse_stream_delivers_latest_event_then_heartbeat() -> None:
    async def scenario() -> None:
        store = SnapshotStore()
        event = await store.publish(_response(1))
        assert event is not None
        stream = sse_stream(
            FakeRequest(),
            store,
            after_event_id=None,
            heartbeat_interval=0.01,
        )

        initial = await anext(stream)
        heartbeat = await anext(stream)
        await stream.aclose()

        assert initial.startswith("id: 1\nevent: live\ndata: ")
        assert heartbeat == ": heartbeat\n\n"

    asyncio.run(scenario())


def test_sse_stream_replays_events_after_last_event_id_and_stops_on_disconnect() -> None:
    async def scenario() -> None:
        store = SnapshotStore()
        first = await store.publish(_response(1))
        second = await store.publish(_response(2, queue_count=1))
        assert first is not None and second is not None
        stream = sse_stream(
            FakeRequest(disconnect_after=1),
            store,
            after_event_id=first.id,
            heartbeat_interval=1.0,
        )

        replay = await anext(stream)
        assert replay.startswith("id: 2\n")
        try:
            await anext(stream)
        except StopAsyncIteration:
            pass
        else:
            raise AssertionError("SSE stream did not stop after the client disconnected.")

    asyncio.run(scenario())


def test_last_event_id_parser_rejects_invalid_values() -> None:
    from fastapi import HTTPException

    assert _parse_last_event_id(None) is None
    assert _parse_last_event_id("12") == 12
    for invalid in ("abc", "-1"):
        try:
            _parse_last_event_id(invalid)
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError(f"Expected Last-Event-ID {invalid!r} to be rejected.")
