from __future__ import annotations

import queue
import time

from fastapi.testclient import TestClient

from ipi_webview.api.app import create_app
from ipi_webview.api.settings import ApiSettings
from test_api_mapper import _snapshot


class FakeSource:
    def __init__(self) -> None:
        self.updates = queue.Queue()
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True
        self.updates.put(_snapshot())

    def get_update(self, timeout=None):
        return self.updates.get(timeout=timeout)

    def close(self, timeout=5.0) -> None:
        self.closed = True


def _wait_for_live(client: TestClient):
    deadline = time.time() + 1.0
    while time.time() < deadline:
        response = client.get("/api/v1/live")
        if response.status_code == 200:
            return response
        time.sleep(0.01)
    raise AssertionError("API did not publish its first live snapshot.")


def test_rest_api_lifecycle_and_read_only_routes() -> None:
    source = FakeSource()
    settings = ApiSettings(
        critical_subsystems="exposure",
        trusted_hosts="testserver",
        docs_enabled=False,
        _env_file=None,
    )
    app = create_app(settings, source=source)

    with TestClient(app) as client:
        live = _wait_for_live(client)
        assert live.json()["schema_version"] == "1"
        assert live.json()["experiment"]["phase"] == "exposing"
        assert client.get("/api/v1/subsystems").status_code == 200
        assert client.get("/api/v1/cameras").json() == {"schema_version": "1", "items": []}
        assert client.get("/health/live").json() == {"status": "ok", "system_state": None}
        assert client.get("/health/ready").status_code == 200
        assert client.post("/api/v1/live").status_code == 405
        assert client.get("/docs").status_code == 404

    assert source.started is True
    assert source.closed is True


def test_live_returns_503_before_first_snapshot() -> None:
    source = FakeSource()

    def start_without_data() -> None:
        source.started = True

    source.start = start_without_data
    app = create_app(
        ApiSettings(trusted_hosts="testserver", docs_enabled=False, _env_file=None),
        source=source,
    )
    with TestClient(app) as client:
        assert client.get("/api/v1/live").status_code == 503
        assert client.get("/health/ready").status_code == 503