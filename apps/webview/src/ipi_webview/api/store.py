from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass
from typing import Any

from ipi_webview.api.models import LiveResponse


@dataclass(frozen=True, slots=True)
class LiveEvent:
    id: int
    snapshot: LiveResponse

    def to_sse(self) -> str:
        return f"id: {self.id}\nevent: live\ndata: {self.snapshot.model_dump_json()}\n\n"


def semantic_fingerprint(snapshot: LiveResponse) -> str:
    payload: dict[str, Any] = snapshot.model_dump(mode="json")
    payload.pop("revision", None)
    payload.pop("generated_at", None)
    for source_name, source in payload.get("sources", {}).items():
        if source_name != "subsystems":
            source.pop("observed_at", None)
        source.pop("attempted_at", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class SnapshotStore:
    def __init__(self, event_buffer_size: int = 100) -> None:
        if event_buffer_size < 1:
            raise ValueError("Event buffer size must be at least one.")
        self._condition = asyncio.Condition()
        self._events: deque[LiveEvent] = deque(maxlen=event_buffer_size)
        self._latest: LiveResponse | None = None
        self._last_fingerprint: str | None = None
        self._next_event_id = 1

    async def publish(self, snapshot: LiveResponse) -> LiveEvent | None:
        fingerprint = semantic_fingerprint(snapshot)
        async with self._condition:
            self._latest = snapshot
            if fingerprint == self._last_fingerprint:
                return None

            event = LiveEvent(self._next_event_id, snapshot)
            self._next_event_id += 1
            self._last_fingerprint = fingerprint
            self._events.append(event)
            self._condition.notify_all()
            return event

    async def latest(self) -> LiveResponse | None:
        async with self._condition:
            return self._latest

    async def replay(self, after_event_id: int | None) -> tuple[LiveEvent, ...]:
        async with self._condition:
            return self._replay_unlocked(after_event_id)

    async def wait_for_events(
        self,
        after_event_id: int | None,
        timeout: float,
    ) -> tuple[LiveEvent, ...]:
        async with self._condition:
            replay = self._replay_unlocked(after_event_id)
            if replay:
                return replay
            try:
                await asyncio.wait_for(self._condition.wait(), timeout=timeout)
            except TimeoutError:
                return ()
            return self._replay_unlocked(after_event_id)

    def _replay_unlocked(self, after_event_id: int | None) -> tuple[LiveEvent, ...]:
        if not self._events:
            return ()
        if after_event_id is None:
            return (self._events[-1],)
        if after_event_id < self._events[0].id - 1 or after_event_id > self._events[-1].id:
            return (self._events[-1],)
        return tuple(event for event in self._events if event.id > after_event_id)
