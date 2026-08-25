from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from typing import Any, Protocol

from chamber_ctl.subsystems import uuids
from ipi_ecs.dds import client, subsystem, types

from ipi_webview.dds.codecs import (
    decode_batch_controller_state,
    decode_experiment_reasons,
    decode_experiment_state,
    decode_queue,
)
from ipi_webview.dds.events import DataSource, TransportEvent
from ipi_webview.dds.models import (
    StageState,
    StatusSeverity,
    SubsystemStatus,
    SubsystemStatusItem,
)


EventSink = Callable[[TransportEvent], None]


class LiveDdsTransport(Protocol):
    def start(self) -> None: ...

    def poll_queue(self) -> None: ...

    def poll_current_slot(self) -> None: ...

    def poll_subsystems(self) -> None: ...

    def close(self) -> None: ...


def _known_subsystems() -> tuple[tuple[str, uuid.UUID], ...]:
    known = []
    for constant_name, value in vars(uuids).items():
        if constant_name.startswith("UUID_") and isinstance(value, uuid.UUID):
            label = constant_name.removeprefix("UUID_").replace("_", " ").title()
            known.append((label, value))
    return tuple(known)


def _bytes_value(value: Any, field_name: str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview, list)):
        try:
            return bytes(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} is not byte-compatible.") from exc
    raise ValueError(f"{field_name} must be bytes.")


def _float_value(value: Any, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric.") from exc


def _stage_position(value: Any) -> tuple[float, float]:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError("Stage position must contain exactly two values.")
    return (_float_value(value[0], "Stage theta"), _float_value(value[1], "Stage z"))


def _stage_state(value: Any) -> StageState:
    try:
        return StageState(int(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("Stage state is unknown.") from exc


def _current_slot(value: Any) -> int:
    try:
        slot = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Current sample slot must be an integer.") from exc
    if slot < -1:
        raise ValueError("Current sample slot cannot be less than -1.")
    return slot


def _format_awaiter_error(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    reason = kwargs.get("reason")
    state = kwargs.get("state")
    if reason is None and args:
        reason = args[-1]
    if isinstance(reason, bytes):
        reason = reason.decode("utf-8", errors="replace")
    if reason not in (None, ""):
        return str(reason)
    if state is not None:
        return f"DDS read failed with state {state}."
    return "DDS read failed."


class EcsDdsTransport:
    def __init__(
        self,
        host: str,
        sink: EventSink,
        *,
        client_factory: Callable[..., Any] = client.DDSClient,
        wall_clock: Callable[[], float] = time.time,
        subsystem_poll_timeout: float = 3.0,
    ) -> None:
        if subsystem_poll_timeout <= 0:
            raise ValueError("Subsystem poll timeout must be greater than zero.")
        self._host = host
        self._sink = sink
        self._client_factory = client_factory
        self._wall_clock = wall_clock
        self._subsystem_poll_timeout = subsystem_poll_timeout

        self._client = None
        self._handle = None
        self._closed = False
        self._configured = False
        self._generation = 0
        self._pending_reads: dict[DataSource, int] = {}
        self._lock = threading.Lock()

        self._experiment_kv = None
        self._reasons_kv = None
        self._dose_kv = None
        self._time_kv = None
        self._queue_kv = None
        self._batch_controller_kv = None
        self._stage_position_kv = None
        self._stage_state_kv = None
        self._current_slot_kv = None

    def start(self) -> None:
        if self._client is not None:
            return
        self._client = self._client_factory(uuid.uuid4(), ip=self._host)
        self._client.when_ready().then(self._on_ready).catch(self._on_ready_error)

    def _on_ready(self, *_args, **_kwargs) -> None:
        with self._lock:
            if self._closed:
                return
            self._generation += 1
            self._pending_reads.clear()

        if not self._configured:
            subsystem_uuid = uuid.uuid4()
            self._handle = self._client.register_subsystem(
                f"__chamber_webview_{subsystem_uuid}",
                subsystem_uuid,
                temporary=True,
            )
            self._configure_endpoints()
            self._configured = True

        now = self._wall_clock()
        self._sink(TransportEvent(DataSource.TRANSPORT, now, now, value=True))
        self._poll_initial_values()
        self.poll_subsystems()

    def _on_ready_error(self, *args, **kwargs) -> None:
        now = self._wall_clock()
        self._sink(
            TransportEvent(
                DataSource.TRANSPORT,
                now,
                now,
                error=_format_awaiter_error(args, kwargs),
            )
        )

    def _configure_endpoints(self) -> None:
        self._experiment_kv = self._remote_kv(
            uuids.UUID_EXPOSURE_CONTROLLER,
            types.ByteTypeSpecifier(),
            b"experiment_state",
            published=True,
        )
        self._subscribe(self._experiment_kv, DataSource.EXPERIMENT, decode_experiment_state)

        self._reasons_kv = self._remote_kv(
            uuids.UUID_EXPOSURE_CONTROLLER,
            types.ByteTypeSpecifier(),
            b"experiment_reasons",
            published=True,
        )
        self._subscribe(self._reasons_kv, DataSource.EXPERIMENT_REASONS, decode_experiment_reasons)

        self._dose_kv = self._remote_kv(
            uuids.UUID_EUV_ACQUISITION_CONTROLLER,
            types.FloatTypeSpecifier(),
            b"cur_dose",
            published=True,
        )
        self._subscribe(self._dose_kv, DataSource.CURRENT_DOSE, lambda value: _float_value(value, "Current dose"))

        self._time_kv = self._remote_kv(
            uuids.UUID_EUV_ACQUISITION_CONTROLLER,
            types.FloatTypeSpecifier(),
            b"cur_time",
            published=True,
        )
        self._subscribe(self._time_kv, DataSource.CURRENT_TIME, lambda value: _float_value(value, "Current time"))

        self._queue_kv = self._remote_kv(
            uuids.UUID_EXPERIMENT_QUEUE_CONTROLLER,
            types.ByteTypeSpecifier(),
            b"queue",
            published=False,
        )

        self._batch_controller_kv = self._remote_kv(
            uuids.UUID_EXPOSURE_BATCH_CONTROLLER,
            types.ByteTypeSpecifier(),
            b"state",
            published=True,
        )
        self._subscribe(
            self._batch_controller_kv,
            DataSource.BATCH_CONTROLLER,
            decode_batch_controller_state,
        )

        self._stage_position_kv = self._remote_kv(
            uuids.UUID_SAMPLE_MOTION_CONTROLLER,
            types.VectorTypeSpecifier(types.FloatTypeSpecifier(), 2),
            b"position",
            published=True,
        )
        self._subscribe(self._stage_position_kv, DataSource.STAGE_POSITION, _stage_position)

        self._stage_state_kv = self._remote_kv(
            uuids.UUID_SAMPLE_MOTION_CONTROLLER,
            types.IntegerTypeSpecifier(),
            b"status",
            published=True,
        )
        self._subscribe(self._stage_state_kv, DataSource.STAGE_STATE, _stage_state)

        self._current_slot_kv = self._remote_kv(
            uuids.UUID_SAMPLE_MOTION_CONTROLLER,
            types.IntegerTypeSpecifier(),
            b"sample",
            published=False,
        )

    def _remote_kv(self, target_uuid, value_type, key: bytes, *, published: bool):
        descriptor = subsystem.KVDescriptor(value_type, key, published, True, False)
        return self._handle.add_remote_kv(target_uuid, descriptor)

    def _subscribe(self, remote_kv, source: DataSource, decoder: Callable[[Any], Any]) -> None:
        def on_value(value: Any) -> None:
            now = self._wall_clock()
            try:
                decoded = decoder(value)
            except Exception as exc:
                self._sink(TransportEvent(source, now, now, error=f"{type(exc).__name__}: {exc}"))
            else:
                self._sink(TransportEvent(source, now, now, value=decoded))

        remote_kv.on_new_data_received(on_value)

    def _poll_initial_values(self) -> None:
        self._request_read(self._experiment_kv, DataSource.EXPERIMENT, decode_experiment_state)
        self._request_read(self._reasons_kv, DataSource.EXPERIMENT_REASONS, decode_experiment_reasons)
        self._request_read(
            self._dose_kv,
            DataSource.CURRENT_DOSE,
            lambda value: _float_value(value, "Current dose"),
        )
        self._request_read(
            self._time_kv,
            DataSource.CURRENT_TIME,
            lambda value: _float_value(value, "Current time"),
        )
        self._request_read(self._stage_position_kv, DataSource.STAGE_POSITION, _stage_position)
        self._request_read(self._stage_state_kv, DataSource.STAGE_STATE, _stage_state)
        self.poll_queue()
        self._request_read(
            self._batch_controller_kv,
            DataSource.BATCH_CONTROLLER,
            decode_batch_controller_state,
        )
        self.poll_current_slot()

    def poll_queue(self) -> None:
        self._request_read(self._queue_kv, DataSource.QUEUE, lambda value: decode_queue(_bytes_value(value, "Queue")))

    def poll_current_slot(self) -> None:
        self._request_read(self._current_slot_kv, DataSource.CURRENT_SLOT, _current_slot)

    def _request_read(self, remote_kv, source: DataSource, decoder: Callable[[Any], Any]) -> None:
        if remote_kv is None:
            return

        with self._lock:
            if self._closed or source in self._pending_reads:
                return
            generation = self._generation
            self._pending_reads[source] = generation

        sampled_at = self._wall_clock()
        try:
            awaiter = remote_kv.try_get()
        except Exception as exc:
            self._complete_read(source, generation)
            now = self._wall_clock()
            self._sink(TransportEvent(source, now, sampled_at, error=f"{type(exc).__name__}: {exc}"))
            return

        if awaiter is None:
            self._complete_read(source, generation)
            now = self._wall_clock()
            self._sink(TransportEvent(source, now, sampled_at, error="DDS read could not be started."))
            return

        def on_value(value: Any) -> None:
            if not self._complete_read(source, generation):
                return
            now = self._wall_clock()
            try:
                decoded = decoder(value)
            except Exception as exc:
                self._sink(TransportEvent(source, now, sampled_at, error=f"{type(exc).__name__}: {exc}"))
            else:
                self._sink(TransportEvent(source, now, sampled_at, value=decoded))

        def on_error(*args, **kwargs) -> None:
            if not self._complete_read(source, generation):
                return
            now = self._wall_clock()
            self._sink(
                TransportEvent(
                    source,
                    now,
                    sampled_at,
                    error=_format_awaiter_error(args, kwargs),
                )
            )

        awaiter.then(on_value).catch(on_error)

    def _complete_read(self, source: DataSource, generation: int) -> bool:
        with self._lock:
            if self._closed or self._pending_reads.get(source) != generation:
                return False
            self._pending_reads.pop(source, None)
            return True

    def poll_subsystems(self) -> None:
        if self._handle is None:
            return

        sampled_at = self._wall_clock()
        with self._lock:
            if self._closed or DataSource.SUBSYSTEMS in self._pending_reads:
                return
            generation = self._generation
            self._pending_reads[DataSource.SUBSYSTEMS] = generation

        try:
            known_uuids = {subsystem_uuid for _, subsystem_uuid in _known_subsystems()}
            remotes_by_uuid = {}
            for remote, _cached_state in self._handle.get_all():
                info = remote.get_info()
                subsystem_uuid = info.get_uuid()
                if subsystem_uuid in known_uuids:
                    remotes_by_uuid[subsystem_uuid] = (info, remote)
        except Exception as exc:
            self._complete_read(DataSource.SUBSYSTEMS, generation)
            now = self._wall_clock()
            self._sink(TransportEvent(DataSource.SUBSYSTEMS, now, sampled_at, error=f"{type(exc).__name__}: {exc}"))
            return

        if not remotes_by_uuid:
            self._emit_subsystem_rows({}, generation, sampled_at)
            return

        fresh_states = {}
        remaining = len(remotes_by_uuid)
        aggregate_lock = threading.Lock()
        finished = False

        def finish() -> None:
            nonlocal finished
            with aggregate_lock:
                if finished:
                    return
                finished = True
                resolved_states = dict(fresh_states)
            timer.cancel()
            unresolved = set(remotes_by_uuid) - set(resolved_states)
            if unresolved:
                if not self._complete_read(DataSource.SUBSYSTEMS, generation):
                    return
                names = sorted(
                    remotes_by_uuid[subsystem_uuid][0].get_name() or str(subsystem_uuid)
                    for subsystem_uuid in unresolved
                )
                now = self._wall_clock()
                self._sink(
                    TransportEvent(
                        DataSource.SUBSYSTEMS,
                        now,
                        sampled_at,
                        error=f"Status read timed out or failed for: {', '.join(names)}",
                    )
                )
                return
            self._emit_subsystem_rows(
                {
                    current_uuid: (info, resolved_states.get(current_uuid))
                    for current_uuid, (info, _remote) in remotes_by_uuid.items()
                },
                generation,
                sampled_at,
            )

        def complete(subsystem_uuid, state) -> None:
            nonlocal remaining, finished
            emit = False
            with aggregate_lock:
                if finished:
                    return
                if state is not None:
                    fresh_states[subsystem_uuid] = state
                remaining -= 1
                emit = remaining == 0
            if emit:
                finish()

        timer = threading.Timer(self._subsystem_poll_timeout, finish)
        timer.daemon = True
        timer.start()

        for subsystem_uuid, (_info, remote) in remotes_by_uuid.items():
            try:
                awaiter = remote.get_status()
            except Exception:
                complete(subsystem_uuid, None)
                continue
            if awaiter is None:
                complete(subsystem_uuid, None)
                continue
            awaiter.then(
                lambda state, current_uuid=subsystem_uuid: complete(current_uuid, state)
            ).catch(
                lambda *_args, current_uuid=subsystem_uuid, **_kwargs: complete(current_uuid, None)
            )

    def _emit_subsystem_rows(self, live_by_uuid, generation: int, sampled_at: float) -> None:
        if not self._complete_read(DataSource.SUBSYSTEMS, generation):
            return

        now = self._wall_clock()
        try:
            rows = []
            for default_name, subsystem_uuid in _known_subsystems():
                live = live_by_uuid.get(subsystem_uuid)
                if live is None:
                    rows.append(SubsystemStatus(subsystem_uuid, default_name, False, ()))
                    continue

                info, state = live
                if state is None:
                    rows.append(SubsystemStatus(subsystem_uuid, info.get_name() or default_name, False, ()))
                    continue
                status_items = tuple(
                    SubsystemStatusItem(
                        severity=StatusSeverity(item.get_severity()),
                        code=item.get_code(),
                        message=item.get_message() or "",
                    )
                    for item in state.get_status_items()
                )
                rows.append(
                    SubsystemStatus(
                        uuid=subsystem_uuid,
                        name=info.get_name() or default_name,
                        connected=state.get_status() == subsystem.SubsystemStatus.STATE_ALIVE,
                        status_items=status_items,
                    )
                )
        except Exception as exc:
            self._sink(TransportEvent(DataSource.SUBSYSTEMS, now, sampled_at, error=f"{type(exc).__name__}: {exc}"))
        else:
            self._sink(TransportEvent(DataSource.SUBSYSTEMS, now, sampled_at, value=tuple(rows)))

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._pending_reads.clear()
        if self._client is not None:
            self._client.close()
