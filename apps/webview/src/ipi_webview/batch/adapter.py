from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from ipi_webview.batch.history import ExperimentHistoryAdapter, ExperimentHistoryConfig
from ipi_webview.batch.models import ExperimentHistorySnapshot, LiveBatchSnapshot
from ipi_webview.batch.projector import project_batch
from ipi_webview.dds import DdsLiveSnapshot, EcsLiveAdapter, EcsLiveAdapterConfig


class DdsSource(Protocol):
    def start(self) -> None: ...

    def get_update(self, timeout: float | None = None) -> DdsLiveSnapshot: ...

    def close(self, timeout: float = 5.0) -> None: ...


class HistorySource(Protocol):
    def start(self) -> None: ...

    def request_refresh(self) -> None: ...

    def get_update(self, timeout: float | None = None) -> ExperimentHistorySnapshot: ...

    def close(self, timeout: float = 5.0) -> None: ...


@dataclass(frozen=True, slots=True)
class LiveBatchAdapterConfig:
    dds: EcsLiveAdapterConfig = EcsLiveAdapterConfig()
    history: ExperimentHistoryConfig = ExperimentHistoryConfig()


DdsFactory = Callable[[EcsLiveAdapterConfig], DdsSource]
HistoryFactory = Callable[[ExperimentHistoryConfig], HistorySource]


class LiveBatchAdapter:
    def __init__(
        self,
        config: LiveBatchAdapterConfig | None = None,
        *,
        dds_factory: DdsFactory = EcsLiveAdapter,
        history_factory: HistoryFactory = ExperimentHistoryAdapter,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config or LiveBatchAdapterConfig()
        self._dds = dds_factory(self.config.dds)
        self._history = history_factory(self.config.history)
        self._wall_clock = wall_clock

        self._commands: queue.Queue[tuple[str, object] | object] = queue.Queue()
        self._updates: queue.Queue[LiveBatchSnapshot] = queue.Queue(maxsize=1)
        self._stop_token = object()
        self._stop_forwarders = threading.Event()
        self._thread: threading.Thread | None = None
        self._forwarders: list[threading.Thread] = []
        self._lifecycle_lock = threading.Lock()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_forwarders.clear()
            self._thread = threading.Thread(target=self._run, name="chamber-webview-batch", daemon=True)
            self._thread.start()

    def get_update(self, timeout: float | None = None) -> LiveBatchSnapshot:
        return self._updates.get(timeout=timeout)

    def close(self, timeout: float = 5.0) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            if thread is None:
                return
            if thread.is_alive():
                self._commands.put(self._stop_token)
        thread.join(timeout=timeout)
        if thread.is_alive():
            raise TimeoutError("Timed out while stopping the live batch adapter.")
        with self._lifecycle_lock:
            self._thread = None

    def _run(self) -> None:
        latest_dds: DdsLiveSnapshot | None = None
        latest_history: ExperimentHistorySnapshot | None = None
        previous_run_uuid: UUID | None = None
        has_seen_dds = False
        revision = 0

        self._dds.start()
        self._history.start()
        self._forwarders = [
            threading.Thread(
                target=self._forward_updates,
                args=("dds", self._dds),
                name="chamber-webview-batch-dds-forwarder",
                daemon=True,
            ),
            threading.Thread(
                target=self._forward_updates,
                args=("history", self._history),
                name="chamber-webview-batch-history-forwarder",
                daemon=True,
            ),
        ]
        for forwarder in self._forwarders:
            forwarder.start()

        try:
            while True:
                command = self._commands.get()
                if command is self._stop_token:
                    break

                kind, value = command
                if kind == "dds" and isinstance(value, DdsLiveSnapshot):
                    latest_dds = value
                    run_uuid = self._run_uuid(value)
                    if has_seen_dds and run_uuid != previous_run_uuid:
                        self._history.request_refresh()
                    elif not has_seen_dds and run_uuid is not None:
                        self._history.request_refresh()
                    previous_run_uuid = run_uuid
                    has_seen_dds = True
                elif kind == "history" and isinstance(value, ExperimentHistorySnapshot):
                    latest_history = value
                else:
                    continue

                if latest_dds is None or latest_history is None:
                    continue
                revision += 1
                emitted_at = self._wall_clock()
                self._publish(
                    LiveBatchSnapshot(
                        revision=revision,
                        emitted_at=emitted_at,
                        dds=latest_dds,
                        history=latest_history,
                        batch=project_batch(latest_dds, latest_history),
                    )
                )
        finally:
            self._stop_forwarders.set()
            self._dds.close()
            self._history.close()
            for forwarder in self._forwarders:
                forwarder.join(timeout=1.5)

    def _forward_updates(self, kind: str, source: DdsSource | HistorySource) -> None:
        while not self._stop_forwarders.is_set():
            try:
                update = source.get_update(timeout=0.25)
            except queue.Empty:
                continue
            self._commands.put((kind, update))

    @staticmethod
    def _run_uuid(snapshot: DdsLiveSnapshot) -> UUID | None:
        state = snapshot.experiment.value
        if state is None or state.run is None:
            return None
        return state.run.uuid

    def _publish(self, snapshot: LiveBatchSnapshot) -> None:
        try:
            self._updates.put_nowait(snapshot)
            return
        except queue.Full:
            pass
        try:
            self._updates.get_nowait()
        except queue.Empty:
            pass
        self._updates.put_nowait(snapshot)
