from __future__ import annotations

import asyncio
import queue
from typing import Protocol

from ipi_webview.api.mapper import PublicSnapshotMapper
from ipi_webview.api.store import SnapshotStore
from ipi_webview.batch.models import LiveBatchSnapshot


class SnapshotSource(Protocol):
    def start(self) -> None: ...

    def get_update(self, timeout: float | None = None) -> LiveBatchSnapshot: ...

    def close(self, timeout: float = 5.0) -> None: ...


class LiveApiService:
    def __init__(
        self,
        source: SnapshotSource,
        mapper: PublicSnapshotMapper,
        store: SnapshotStore,
    ) -> None:
        self._source = source
        self._mapper = mapper
        self._store = store
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._source.start()
        self._task = asyncio.create_task(self._collect(), name="chamber-webview-api-collector")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await asyncio.to_thread(self._source.close)

    async def _collect(self) -> None:
        while True:
            try:
                snapshot = await asyncio.to_thread(self._source.get_update, 0.5)
            except queue.Empty:
                continue
            public_snapshot = self._mapper.map(snapshot)
            await self._store.publish(public_snapshot)
