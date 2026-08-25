from __future__ import annotations

import queue
import time
from pathlib import Path

from fastapi.testclient import TestClient

from ipi_ecs.logging.journal import JournalWriter
from ipi_webview.api.app import create_app
from ipi_webview.api.settings import ApiSettings


class FakeSource:
    def __init__(self) -> None:
        self.updates = queue.Queue()

    def start(self) -> None:
        pass

    def get_update(self, timeout=None):
        return self.updates.get(timeout=timeout)

    def close(self, timeout=5.0) -> None:
        pass


def _create_log_fixture(log_root: Path) -> tuple[str, float]:
    timestamp = time.time()
    writer = JournalWriter(log_root / "current", commit_interval_s=60)
    event_id = "exposure-event-api"
    try:
        writer.begin_event(event_id=event_id, e_type="RUN", level="INFO", message="Exposure started")
        for index in range(60):
            writer.append(
                {
                    "origin": {"uuid": "origin-api", "ts_ns": int((timestamp + index / 1000) * 1_000_000_000)},
                    "l_type": "REC" if index == 1 else "EXP",
                    "level": "INFO",
                    "msg": f"record-{index}",
                    "data": {"subsystem": "Exposure Controller"},
                }
            )
        writer.end_event(event_id=event_id)
        writer.index.conn.commit()
    finally:
        writer.close()
    return event_id, timestamp


def test_log_routes_expose_buffered_pages_events_and_exposure_context(tmp_path: Path) -> None:
    event_id, timestamp = _create_log_fixture(tmp_path / "logs")
    app = create_app(
        ApiSettings(
            data_path=str(tmp_path / "datasets"),
            log_path=str(tmp_path / "logs"),
            trusted_hosts="testserver",
            docs_enabled=False,
            _env_file=None,
        ),
        source=FakeSource(),
    )

    with TestClient(app) as client:
        archives = client.get("/api/v1/logs/archives")
        entries = client.get("/api/v1/logs/entries", params={"page_size": 50})
        entries_with_records = client.get("/api/v1/logs/entries", params={"page_size": 100, "include_records": True})
        invalid_anchor = client.get("/api/v1/logs/entries", params={"direction": "before"})
        events = client.get("/api/v1/logs/events")
        context = client.get("/api/v1/logs/context", params={"event_id": event_id})
        fallback = client.get(
            "/api/v1/logs/context",
            params={"event_id": "missing", "created_at": timestamp - 1, "ended_at": timestamp + 1},
        )

    assert archives.status_code == 200
    assert archives.json()["items"][0]["name"] == "current"
    assert entries.status_code == 200
    assert len(entries.json()["rows"]) == 50
    assert all(row["l_type"] == "EXP" for row in entries.json()["rows"])
    assert len(entries_with_records.json()["rows"]) == 60
    assert any(row["l_type"] == "REC" for row in entries_with_records.json()["rows"])
    assert invalid_anchor.status_code == 422
    assert events.status_code == 200
    assert events.json()["items"][0]["event_id"] == event_id
    assert context.json()["resolution"] == "event"
    assert context.json()["line_to"] == 59
    assert fallback.json()["resolution"] == "time"


def test_log_routes_are_unavailable_when_no_log_path_is_configured(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("IPI_ECS_LOG_DIR", raising=False)
    monkeypatch.delenv("WEBVIEW_LOG_PATH", raising=False)
    app = create_app(
        ApiSettings(data_path=str(tmp_path / "datasets"), trusted_hosts="testserver", docs_enabled=False, _env_file=None),
        source=FakeSource(),
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/logs/archives")

    assert response.status_code == 503
    assert response.json()["detail"] == "Log browser is not configured."