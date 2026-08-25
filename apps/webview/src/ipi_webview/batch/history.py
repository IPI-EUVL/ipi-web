from __future__ import annotations

import math
import os
import queue
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from ipi_ecs.db.db_library import Library

from ipi_webview.batch.models import ExperimentHistoryRecord, ExperimentHistorySnapshot


class LibraryLike(Protocol):
    def query(self, filters: dict, limit: int | None = None) -> list[Any]: ...

    def close(self) -> None: ...


LibraryFactory = Callable[[str], LibraryLike]


def default_data_path() -> str:
    root = os.environ.get("EUVL_PATH")
    if root:
        return str(Path(root) / "datasets")
    return str(Path.cwd() / "datasets")


@dataclass(frozen=True, slots=True)
class ExperimentHistoryConfig:
    data_path: str = ""
    poll_interval: float = 3.0
    query_limit: int = 50
    experiment_type: str = "exposure"

    def __post_init__(self) -> None:
        if self.poll_interval <= 0:
            raise ValueError("History poll interval must be greater than zero.")
        if self.query_limit <= 0:
            raise ValueError("History query limit must be greater than zero.")
        if not self.experiment_type.strip():
            raise ValueError("Exposure type cannot be empty.")

    @property
    def resolved_data_path(self) -> str:
        return self.data_path or default_data_path()


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _optional_int(value: Any) -> int | None:
    parsed = _optional_float(value)
    if parsed is None or not parsed.is_integer():
        return None
    return int(parsed)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _record_from_entry(entry: Any) -> ExperimentHistoryRecord:
    tags: Mapping[str, Any] = entry.get_tags() or {}
    run_value = tags.get("run")
    try:
        run_uuid = UUID(str(run_value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("Exposure record has an invalid or missing run UUID.") from exc

    return ExperimentHistoryRecord(
        uuid=run_uuid,
        created_at=float(entry.get_timestamp()),
        name=str(entry.get_name() or ""),
        sample_slot=_optional_int(tags.get("sample")),
        target_dose=_optional_float(tags.get("target_dose")),
        target_time=_optional_float(tags.get("target_time")),
        actual_dose=_optional_float(tags.get("dose")),
        actual_time=_optional_float(tags.get("runtime")),
        status=_optional_text(tags.get("status")),
        end_reason=_optional_text(tags.get("abort_reason")),
    )


class ExperimentHistoryAdapter:
    def __init__(
        self,
        config: ExperimentHistoryConfig | None = None,
        *,
        library_factory: LibraryFactory = Library,
        wall_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or ExperimentHistoryConfig()
        self._library_factory = library_factory
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock

        self._commands: queue.Queue[object] = queue.Queue()
        self._updates: queue.Queue[ExperimentHistorySnapshot] = queue.Queue(maxsize=1)
        self._refresh_token = object()
        self._stop_token = object()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()
        self._snapshot = ExperimentHistorySnapshot(
            revision=0,
            emitted_at=self._wall_clock(),
            records=(),
            observed_at=None,
            attempted_at=None,
            error=None,
            query_limit=self.config.query_limit,
            possibly_truncated=False,
        )

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="chamber-webview-history", daemon=True)
            self._thread.start()

    def request_refresh(self) -> None:
        self._commands.put(self._refresh_token)

    def get_update(self, timeout: float | None = None) -> ExperimentHistorySnapshot:
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
            raise TimeoutError("Timed out while stopping the experiment history adapter.")
        with self._lifecycle_lock:
            self._thread = None

    def _run(self) -> None:
        library: LibraryLike | None = None
        next_poll = self._monotonic_clock()
        self._publish(self._snapshot)
        try:
            while True:
                timeout = max(0.0, next_poll - self._monotonic_clock())
                try:
                    command = self._commands.get(timeout=timeout)
                except queue.Empty:
                    command = self._refresh_token

                if command is self._stop_token:
                    break
                if command is not self._refresh_token:
                    continue

                attempted_at = self._wall_clock()
                try:
                    if library is None:
                        library = self._library_factory(self.config.resolved_data_path)
                    entries = library.query(
                        {"tags": {"experiment": self.config.experiment_type}},
                        limit=self.config.query_limit,
                    )
                    records = tuple(_record_from_entry(entry) for entry in entries)
                except Exception as exc:
                    if library is not None:
                        try:
                            library.close()
                        finally:
                            library = None
                    self._snapshot = replace(
                        self._snapshot,
                        revision=self._snapshot.revision + 1,
                        emitted_at=self._wall_clock(),
                        attempted_at=attempted_at,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                else:
                    observed_at = self._wall_clock()
                    self._snapshot = ExperimentHistorySnapshot(
                        revision=self._snapshot.revision + 1,
                        emitted_at=observed_at,
                        records=records,
                        observed_at=observed_at,
                        attempted_at=attempted_at,
                        error=None,
                        query_limit=self.config.query_limit,
                        possibly_truncated=len(records) >= self.config.query_limit,
                    )

                self._publish(self._snapshot)
                next_poll = self._monotonic_clock() + self.config.poll_interval
        finally:
            if library is not None:
                library.close()

    def _publish(self, snapshot: ExperimentHistorySnapshot) -> None:
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
