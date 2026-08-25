from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class LogFilters:
    origin_uuid: str | None = None
    l_type: str | None = None
    level: str | None = None
    min_level: str | None = None
    exclude_types: tuple[str, ...] | None = None
    line_from: int | None = None
    line_to: int | None = None
    since: float | None = None
    until: float | None = None

    def __post_init__(self) -> None:
        if self.line_from is not None and self.line_from < 0:
            raise ValueError("Log line_from cannot be negative.")
        if self.line_to is not None and self.line_to < 0:
            raise ValueError("Log line_to cannot be negative.")
        if self.line_from is not None and self.line_to is not None and self.line_from > self.line_to:
            raise ValueError("Log line_from cannot exceed line_to.")
        if self.since is not None and self.until is not None and self.since > self.until:
            raise ValueError("Log since cannot exceed until.")
        if self.exclude_types is not None:
            if len(self.exclude_types) > 20:
                raise ValueError("Log exclude_types cannot contain more than 20 values.")
            if any(not value or len(value) > 64 for value in self.exclude_types):
                raise ValueError("Log exclude_types values must be between 1 and 64 characters.")


@dataclass(frozen=True, slots=True)
class LogArchive:
    name: str
    is_current: bool
    start_line: int
    end_line_exclusive: int
    start_timestamp: float | None
    end_timestamp: float | None


@dataclass(frozen=True, slots=True)
class LogEntry:
    line: int
    timestamp: float | None
    origin_uuid: str | None
    l_type: str
    level: str
    subsystem: str
    message: str
    record: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LogPage:
    archive: str
    filters: LogFilters
    rows: tuple[LogEntry, ...]
    first_line: int | None
    last_line: int | None
    has_before: bool
    has_after: bool
    at_tail: bool


@dataclass(frozen=True, slots=True)
class LogEvent:
    event_id: str
    e_type: str
    level: str
    message: str
    start_line: int
    end_line: int | None
    start_timestamp: float | None
    end_timestamp: float | None
    data_start: dict[str, Any]
    data_end: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LogContext:
    resolution: Literal["event", "time", "unscoped"]
    archive: str | None
    line_from: int | None
    line_to: int | None
    since: float | None
    until: float | None
    matching_archives: tuple[str, ...]
    message: str | None