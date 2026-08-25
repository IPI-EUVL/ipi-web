from __future__ import annotations

import time
from pathlib import Path

import pytest

from ipi_ecs.logging.journal import JournalWriter
from ipi_webview.logs import LogBrowserRepository, LogBrowserUnavailable, LogFilters


def _record(index: int, *, timestamp: float, l_type: str) -> dict:
    return {
        "origin": {"uuid": f"origin-{index % 3}", "ts_ns": int(timestamp * 1_000_000_000)},
        "l_type": l_type,
        "level": "INFO",
        "msg": f"record-{index}",
        "data": {"subsystem": "Exposure Controller", "index": index},
    }


def _create_current_archive(log_root: Path) -> tuple[str, float]:
    now = time.time()
    writer = JournalWriter(log_root / "current", commit_interval_s=60, segment_update_interval_s=60)
    event_id = "exposure-event-1"
    try:
        writer.begin_event(
            event_id=event_id,
            e_type="RUN",
            level="INFO",
            message="Exposure started",
            data_start={"run": "run-1"},
        )
        for index in range(6):
            writer.append(_record(index, timestamp=now + index / 1000, l_type="REC" if index == 2 else "EXP"))
        writer.end_event(event_id=event_id, data_end={"status": "complete"})
        for index in range(6, 170):
            writer.append(_record(index, timestamp=now + index / 1000, l_type="REC" if index % 4 == 0 else "EXP"))
        writer.index.conn.commit()
    finally:
        writer.close()
    return event_id, now


def test_repository_pages_non_contiguous_filtered_lines_and_resolves_exposure_context(tmp_path: Path) -> None:
    event_id, timestamp = _create_current_archive(tmp_path)
    repository = LogBrowserRepository(tmp_path)
    repository.start()
    try:
        archives = repository.list_archives()
        tail = repository.get_page("current", LogFilters(), direction="tail")
        previous = repository.get_page("current", LogFilters(), direction="before", anchor_line=tail.first_line)
        following = repository.get_page("current", LogFilters(), direction="after", anchor_line=previous.last_line)
        event_context = repository.resolve_context(event_id=event_id, created_at=None, ended_at=None)
        time_context = repository.resolve_context(
            event_id="missing-event",
            created_at=timestamp - 1,
            ended_at=timestamp + 1,
        )
        events = repository.list_events("current")
    finally:
        repository.close()

    assert [(archive.name, archive.is_current) for archive in archives] == [("current", True)]
    assert len(tail.rows) == 100
    assert all(row.l_type == "EXP" for row in tail.rows)
    assert tail.has_before is True
    assert tail.has_after is False
    assert previous.rows[-1].line < tail.rows[0].line
    assert [row.line for row in following.rows] == [row.line for row in tail.rows]
    assert event_context.resolution == "event"
    assert (event_context.archive, event_context.line_from, event_context.line_to) == ("current", 0, 5)
    assert time_context.resolution == "time"
    assert time_context.archive == "current"
    assert events[0].event_id == event_id


def test_repository_reports_unavailable_logs_without_creating_a_current_archive(tmp_path: Path) -> None:
    missing_root = tmp_path / "missing"
    repository = LogBrowserRepository(missing_root)
    repository.start()
    try:
        with pytest.raises(LogBrowserUnavailable, match="unavailable"):
            repository.list_archives()
    finally:
        repository.close()

    assert not missing_root.exists()