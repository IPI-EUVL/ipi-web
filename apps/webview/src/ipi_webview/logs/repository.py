from __future__ import annotations

import queue
import re
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from ipi_ecs.logging.viewer import ArchiveInfo, ArchiveView, LogViewer, QueryOptions, get_subsystem

from ipi_webview.logs.models import LogArchive, LogContext, LogEntry, LogEvent, LogFilters, LogPage


class LogBrowserUnavailable(RuntimeError):
    """The configured ECS log root cannot be read at this time."""


class LogBrowserNotFoundError(LookupError):
    """The requested log archive does not exist."""


_ARCHIVE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_PAGE_SIZE_MINIMUM = 50
_PAGE_SIZE_MAXIMUM = 100


@dataclass(slots=True)
class _Command:
    operation: Callable[[], Any]
    response: queue.Queue[tuple[bool, Any]]


class LogBrowserRepository:
    """Thread-affine, read-only access to ECS log archives."""

    def __init__(self, log_path: str | Path, *, page_size: int = 100) -> None:
        self._log_path = Path(log_path)
        if not str(self._log_path).strip():
            raise ValueError("Log browser path cannot be empty.")
        self._validate_page_size(page_size)
        self._page_size = page_size
        self._commands: queue.Queue[_Command | object] = queue.Queue()
        self._stop_token = object()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()
        self._viewer: LogViewer | None = None
        self._active_archive: str | None = None
        self._active_view: ArchiveView | None = None

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="chamber-webview-logs", daemon=True)
            self._thread.start()

    def close(self, timeout: float = 5.0) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            if thread is None:
                return
            if thread.is_alive():
                self._commands.put(self._stop_token)
        thread.join(timeout=timeout)
        if thread.is_alive():
            raise TimeoutError("Timed out while stopping the log browser repository.")
        with self._lifecycle_lock:
            self._thread = None

    def list_archives(self) -> tuple[LogArchive, ...]:
        return self._invoke(self._list_archives)

    def get_page(
        self,
        archive: str,
        filters: LogFilters,
        *,
        direction: Literal["head", "tail", "before", "after"],
        anchor_line: int | None = None,
        page_size: int | None = None,
    ) -> LogPage:
        selected_page_size = self._page_size if page_size is None else page_size
        self._validate_page_size(selected_page_size)
        if direction in {"before", "after"} and anchor_line is None:
            raise ValueError("Anchored log pages require an anchor line.")
        if anchor_line is not None and anchor_line < 0:
            raise ValueError("Log anchor line cannot be negative.")
        return self._invoke(
            lambda: self._get_page(
                archive,
                filters,
                direction=direction,
                anchor_line=anchor_line,
                page_size=selected_page_size,
            )
        )

    def list_events(self, archive: str, *, limit: int = 200) -> tuple[LogEvent, ...]:
        if not 1 <= limit <= 200:
            raise ValueError("Log event limit must be between 1 and 200.")
        return self._invoke(lambda: self._list_events(archive, limit=limit))

    def resolve_context(
        self,
        *,
        event_id: str | None,
        created_at: float | None,
        ended_at: float | None,
    ) -> LogContext:
        if created_at is not None and ended_at is not None and created_at > ended_at:
            raise ValueError("Log context created_at cannot exceed ended_at.")
        return self._invoke(
            lambda: self._resolve_context(event_id=event_id, created_at=created_at, ended_at=ended_at)
        )

    def _run(self) -> None:
        self._viewer = LogViewer(self._log_path, read_only=True)
        try:
            while True:
                command = self._commands.get()
                if command is self._stop_token:
                    return
                assert isinstance(command, _Command)
                try:
                    command.response.put((True, command.operation()))
                except Exception as exc:
                    command.response.put((False, exc))
        finally:
            if self._active_view is not None:
                self._active_view.close()
                self._active_view = None
            self._active_archive = None
            self._viewer = None

    def _invoke(self, operation: Callable[[], Any]) -> Any:
        with self._lifecycle_lock:
            thread = self._thread
        if thread is None or not thread.is_alive():
            raise LogBrowserUnavailable("Log browser repository is not running.")
        response: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)
        self._commands.put(_Command(operation, response))
        succeeded, value = response.get()
        if succeeded:
            return value
        if isinstance(value, (FileNotFoundError, OSError, sqlite3.Error)):
            raise LogBrowserUnavailable("Configured ECS logs are unavailable.") from value
        raise value

    def _list_archives(self) -> tuple[LogArchive, ...]:
        viewer = self._require_viewer()
        try:
            archives = [self._archive_from_info(viewer.current_archive_info(), is_current=True)]
            if not viewer.is_direct_archive:
                archives.extend(self._archive_from_info(info, is_current=False) for info in viewer.list_archives())
            return tuple(archives)
        except (FileNotFoundError, OSError, sqlite3.Error) as exc:
            raise LogBrowserUnavailable("Configured ECS logs are unavailable.") from exc

    def _get_page(
        self,
        archive: str,
        filters: LogFilters,
        *,
        direction: Literal["head", "tail", "before", "after"],
        anchor_line: int | None,
        page_size: int,
    ) -> LogPage:
        normalized_filters = self._normalize_filters(filters)
        view = self._open_archive(archive)
        options = self._query_options(normalized_filters)
        if direction == "tail":
            line_max = normalized_filters.line_to + 1 if normalized_filters.line_to is not None else view.next_line()
            lines = view.window_before(options, line_max_exclusive=line_max, window=page_size)
        elif direction == "head":
            line_min = normalized_filters.line_from if normalized_filters.line_from is not None else 0
            lines = view.window_after(options, line_min_inclusive=line_min, window=page_size)
        elif direction == "before":
            assert anchor_line is not None
            lines = view.window_before(options, line_max_exclusive=anchor_line, window=page_size)
        else:
            assert anchor_line is not None
            lines = view.window_after(options, line_min_inclusive=anchor_line + 1, window=page_size)

        rows = tuple(self._entry_from_line(line.line, line.record) for line in lines)
        first_line = rows[0].line if rows else None
        last_line = rows[-1].line if rows else None
        has_before = bool(
            first_line is not None
            and view.window_before(options, line_max_exclusive=first_line, window=1)
        )
        has_after = bool(
            last_line is not None
            and view.window_after(options, line_min_inclusive=last_line + 1, window=1)
        )
        return LogPage(
            archive=archive,
            filters=normalized_filters,
            rows=rows,
            first_line=first_line,
            last_line=last_line,
            has_before=has_before,
            has_after=has_after,
            at_tail=not has_after,
        )

    def _list_events(self, archive: str, *, limit: int) -> tuple[LogEvent, ...]:
        view = self._open_archive(archive)
        return tuple(
            LogEvent(
                event_id=event.event_id,
                e_type=event.e_type,
                level=event.level,
                message=event.message,
                start_line=event.start_line,
                end_line=event.end_line,
                start_timestamp=self._seconds(event.start_ts_ns),
                end_timestamp=self._seconds(event.end_ts_ns),
                data_start=event.data_start,
                data_end=event.data_end,
            )
            for event in view.list_events(limit=limit, desc=True)
        )

    def _resolve_context(
        self,
        *,
        event_id: str | None,
        created_at: float | None,
        ended_at: float | None,
    ) -> LogContext:
        archives = self._list_archives()
        if event_id:
            for archive in archives:
                view = self._open_archive(archive.name)
                event = view.get_event(event_id)
                if event is not None:
                    end_line = event.end_line if event.end_line is not None else max(event.start_line, view.next_line() - 1)
                    return LogContext(
                        resolution="event",
                        archive=archive.name,
                        line_from=event.start_line,
                        line_to=end_line,
                        since=self._seconds(event.start_ts_ns),
                        until=self._seconds(event.end_ts_ns),
                        matching_archives=(archive.name,),
                        message=None,
                    )

        overlapping = tuple(
            archive.name
            for archive in archives
            if self._overlaps(archive, created_at=created_at, ended_at=ended_at)
        )
        if overlapping:
            return LogContext(
                resolution="time",
                archive=overlapping[0],
                line_from=None,
                line_to=None,
                since=created_at,
                until=ended_at,
                matching_archives=overlapping,
                message="The exposure event was not indexed; showing the matching log time range.",
            )

        current = next((archive.name for archive in archives if archive.is_current), archives[0].name if archives else None)
        return LogContext(
            resolution="unscoped",
            archive=current,
            line_from=None,
            line_to=None,
            since=None,
            until=None,
            matching_archives=(),
            message="No matching exposure event or log time range was found.",
        )

    def _open_archive(self, archive: str) -> ArchiveView:
        self._validate_archive_name(archive)
        if self._active_archive == archive and self._active_view is not None:
            return self._active_view
        if self._active_view is not None:
            self._active_view.close()
            self._active_view = None
        viewer = self._require_viewer()
        try:
            self._active_view = viewer.open_archive(None if viewer.is_direct_archive else archive)
        except FileNotFoundError as exc:
            raise LogBrowserNotFoundError(f"Log archive {archive!r} was not found.") from exc
        self._active_archive = archive
        return self._active_view

    def _require_viewer(self) -> LogViewer:
        if self._viewer is None:
            raise LogBrowserUnavailable("Log browser repository is not running.")
        return self._viewer

    @staticmethod
    def _validate_archive_name(archive: str) -> None:
        if archive != "current" and not _ARCHIVE_NAME.fullmatch(archive):
            raise ValueError("Log archive name is invalid.")

    @staticmethod
    def _validate_page_size(page_size: int) -> None:
        if not _PAGE_SIZE_MINIMUM <= page_size <= _PAGE_SIZE_MAXIMUM:
            raise ValueError("Log page size must be between 50 and 100.")

    @staticmethod
    def _seconds(timestamp_ns: int | None) -> float | None:
        return None if timestamp_ns is None or timestamp_ns <= 0 else timestamp_ns / 1_000_000_000

    @staticmethod
    def _archive_from_info(info: ArchiveInfo, *, is_current: bool) -> LogArchive:
        return LogArchive(
            name=info.name,
            is_current=is_current,
            start_line=info.start_line,
            end_line_exclusive=info.end_line_exclusive,
            start_timestamp=LogBrowserRepository._seconds(info.start_ts_ns),
            end_timestamp=LogBrowserRepository._seconds(info.end_ts_ns),
        )

    @staticmethod
    def _entry_from_line(line: int, record: dict[str, Any]) -> LogEntry:
        origin = record.get("origin")
        origin_data = origin if isinstance(origin, dict) else {}
        timestamp = origin_data.get("ts_ns")
        return LogEntry(
            line=line,
            timestamp=LogBrowserRepository._seconds(timestamp if isinstance(timestamp, int) else None),
            origin_uuid=origin_data.get("uuid") if isinstance(origin_data.get("uuid"), str) else None,
            l_type=str(record.get("l_type") or "?"),
            level=str(record.get("level") or "?"),
            subsystem=get_subsystem(record),
            message=str(record.get("msg") or ""),
            record=record,
        )

    @staticmethod
    def _normalize_filters(filters: LogFilters) -> LogFilters:
        if filters.exclude_types is None and filters.l_type is None:
            return LogFilters(
                origin_uuid=filters.origin_uuid,
                l_type=filters.l_type,
                level=filters.level,
                min_level=filters.min_level,
                exclude_types=("REC",),
                line_from=filters.line_from,
                line_to=filters.line_to,
                since=filters.since,
                until=filters.until,
            )
        return filters

    @staticmethod
    def _query_options(filters: LogFilters) -> QueryOptions:
        return QueryOptions(
            uuid=filters.origin_uuid,
            line_from=filters.line_from,
            line_to=filters.line_to,
            since=LogBrowserRepository._time_text(filters.since),
            until=LogBrowserRepository._time_text(filters.until),
            l_type=filters.l_type,
            exclude_types=list(filters.exclude_types) if filters.exclude_types is not None else None,
            level=filters.level,
            min_level=filters.min_level,
        )

    @staticmethod
    def _time_text(value: float | None) -> str | None:
        return None if value is None else datetime.fromtimestamp(value, tz=timezone.utc).isoformat()

    @staticmethod
    def _overlaps(archive: LogArchive, *, created_at: float | None, ended_at: float | None) -> bool:
        if created_at is None and ended_at is None:
            return False
        if archive.start_timestamp is None or archive.end_timestamp is None:
            return archive.is_current and ended_at is None
        range_start = created_at if created_at is not None else float("-inf")
        range_end = ended_at if ended_at is not None else float("inf")
        return archive.start_timestamp <= range_end and archive.end_timestamp >= range_start