from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from chamber_ctl import ECS_IP

from ipi_webview.dds.events import DataSource, TransportEvent
from ipi_webview.dds.models import DdsLiveSnapshot, ObservedValue
from ipi_webview.dds.transport import EcsDdsTransport, LiveDdsTransport


@dataclass(frozen=True, slots=True)
class EcsLiveAdapterConfig:
    host: str = ECS_IP
    queue_poll_interval: float = 1.0
    current_slot_poll_interval: float = 1.0
    subsystem_poll_interval: float = 1.5
    subsystem_poll_timeout: float = 3.0
    publish_interval: float = 0.25

    def __post_init__(self) -> None:
        intervals = (
            self.queue_poll_interval,
            self.current_slot_poll_interval,
            self.subsystem_poll_interval,
            self.subsystem_poll_timeout,
            self.publish_interval,
        )
        if not self.host.strip():
            raise ValueError("DDS host cannot be empty.")
        if any(interval <= 0 for interval in intervals):
            raise ValueError("Adapter intervals must be greater than zero.")


TransportFactory = Callable[[EcsLiveAdapterConfig, Callable[[TransportEvent], None]], LiveDdsTransport]


def _default_transport_factory(
    config: EcsLiveAdapterConfig,
    sink: Callable[[TransportEvent], None],
) -> LiveDdsTransport:
    return EcsDdsTransport(config.host, sink, subsystem_poll_timeout=config.subsystem_poll_timeout)


def _empty_snapshot(now: float) -> DdsLiveSnapshot:
    return DdsLiveSnapshot(
        revision=0,
        emitted_at=now,
        transport_ready=ObservedValue(),
        experiment=ObservedValue(),
        experiment_reasons=ObservedValue(),
        current_dose=ObservedValue(),
        current_time=ObservedValue(),
        queue=ObservedValue(),
        stage_position=ObservedValue(),
        stage_state=ObservedValue(),
        current_slot=ObservedValue(),
        subsystems=ObservedValue(),
        batch_controller=ObservedValue(),
    )


class EcsLiveAdapter:
    _FIELD_BY_SOURCE = {
        DataSource.TRANSPORT: "transport_ready",
        DataSource.EXPERIMENT: "experiment",
        DataSource.EXPERIMENT_REASONS: "experiment_reasons",
        DataSource.CURRENT_DOSE: "current_dose",
        DataSource.CURRENT_TIME: "current_time",
        DataSource.QUEUE: "queue",
        DataSource.BATCH_CONTROLLER: "batch_controller",
        DataSource.STAGE_POSITION: "stage_position",
        DataSource.STAGE_STATE: "stage_state",
        DataSource.CURRENT_SLOT: "current_slot",
        DataSource.SUBSYSTEMS: "subsystems",
    }

    def __init__(
        self,
        config: EcsLiveAdapterConfig | None = None,
        *,
        transport_factory: TransportFactory = _default_transport_factory,
        wall_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or EcsLiveAdapterConfig()
        self._transport_factory = transport_factory
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock

        self._commands: queue.Queue[TransportEvent | object] = queue.Queue()
        self._updates: queue.Queue[DdsLiveSnapshot] = queue.Queue(maxsize=1)
        self._stop_token = object()
        self._thread: threading.Thread | None = None
        self._transport: LiveDdsTransport | None = None
        self._lifecycle_lock = threading.Lock()

        self._snapshot = _empty_snapshot(self._wall_clock())
        self._progress_epoch: float | None = None
        self._dirty = False

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="chamber-webview-dds", daemon=True)
            self._thread.start()

    def get_update(self, timeout: float | None = None) -> DdsLiveSnapshot:
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
            raise TimeoutError("Timed out while stopping the ECS live adapter.")
        with self._lifecycle_lock:
            self._thread = None

    def _run(self) -> None:
        now_mono = self._monotonic_clock()
        next_queue_poll = now_mono
        next_slot_poll = now_mono
        next_subsystem_poll = now_mono
        next_publish = now_mono + self.config.publish_interval

        self._publish(self._snapshot)
        try:
            self._transport = self._transport_factory(self.config, self._commands.put)
            self._transport.start()

            while True:
                now_mono = self._monotonic_clock()
                if now_mono >= next_queue_poll:
                    self._transport.poll_queue()
                    next_queue_poll = now_mono + self.config.queue_poll_interval
                if now_mono >= next_slot_poll:
                    self._transport.poll_current_slot()
                    next_slot_poll = now_mono + self.config.current_slot_poll_interval
                if now_mono >= next_subsystem_poll:
                    self._transport.poll_subsystems()
                    next_subsystem_poll = now_mono + self.config.subsystem_poll_interval

                if self._dirty and now_mono >= next_publish:
                    self._emit_changed_snapshot()
                    next_publish = now_mono + self.config.publish_interval

                deadlines = [next_queue_poll, next_slot_poll, next_subsystem_poll]
                if self._dirty:
                    deadlines.append(next_publish)
                timeout = max(0.0, min(deadlines) - self._monotonic_clock())
                try:
                    command = self._commands.get(timeout=timeout)
                except queue.Empty:
                    continue

                if command is self._stop_token:
                    break
                self._apply_event(command)

                while True:
                    try:
                        command = self._commands.get_nowait()
                    except queue.Empty:
                        break
                    if command is self._stop_token:
                        return
                    self._apply_event(command)
        except Exception as exc:
            now = self._wall_clock()
            self._apply_event(
                TransportEvent(
                    DataSource.TRANSPORT,
                    now,
                    now,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            self._emit_changed_snapshot()
        finally:
            if self._transport is not None:
                self._transport.close()

    def _apply_event(self, event: TransportEvent | object) -> None:
        if not isinstance(event, TransportEvent):
            return

        field_name = self._FIELD_BY_SOURCE[event.source]
        current: ObservedValue[Any] = getattr(self._snapshot, field_name)

        if event.error is not None and event.source is DataSource.TRANSPORT:
            updated = ObservedValue(
                value=False,
                observed_at=event.received_at,
                attempted_at=event.received_at,
                error=event.error,
            )
        elif event.error is not None:
            updated = replace(current, attempted_at=event.received_at, error=event.error)
        else:
            if event.source in (DataSource.CURRENT_DOSE, DataSource.CURRENT_TIME):
                if self._progress_epoch is not None and event.sampled_at < self._progress_epoch:
                    return
            updated = ObservedValue(
                value=event.value,
                observed_at=event.received_at,
                attempted_at=event.received_at,
                error=None,
            )

        if event.source is DataSource.EXPERIMENT and event.error is None:
            previous_uuid = self._run_uuid(current.value)
            next_uuid = self._run_uuid(event.value)
            if previous_uuid != next_uuid:
                self._progress_epoch = event.received_at
                self._snapshot = replace(
                    self._snapshot,
                    current_dose=ObservedValue(attempted_at=event.received_at),
                    current_time=ObservedValue(attempted_at=event.received_at),
                )

        self._snapshot = replace(self._snapshot, **{field_name: updated})
        self._update_transport_health(event)
        self._dirty = True

    def _update_transport_health(self, event: TransportEvent) -> None:
        if event.source is DataSource.TRANSPORT or event.error is not None:
            return
        self._snapshot = replace(
            self._snapshot,
            transport_ready=ObservedValue(
                value=True,
                observed_at=event.received_at,
                attempted_at=event.received_at,
                error=None,
            ),
        )

    @staticmethod
    def _run_uuid(experiment_state):
        if experiment_state is None or experiment_state.run is None:
            return None
        return experiment_state.run.uuid

    def _emit_changed_snapshot(self) -> None:
        if not self._dirty:
            return
        self._snapshot = replace(
            self._snapshot,
            revision=self._snapshot.revision + 1,
            emitted_at=self._wall_clock(),
        )
        self._dirty = False
        self._publish(self._snapshot)

    def _publish(self, snapshot: DdsLiveSnapshot) -> None:
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
