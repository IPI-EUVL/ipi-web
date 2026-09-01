from __future__ import annotations

import queue
import time
import uuid
import json
import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
import numpy as np
import pytest

from ipi_ecs.db.db_library import Library
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


def _create_run(library: Library, run_uuid: uuid.UUID, index: int) -> None:
    entry = library.create_entry(f"Run {index}", "Fixture")
    entry.set_tag("experiment", "exposure")
    entry.set_tag("run", run_uuid.hex)
    entry.set_tag("dose", float(index))
    entry.set_tag("runtime", float(index + 1))
    entry.set_tag("operator", "operator-a")
    with entry.resource("run.json", "run_state", "w") as resource:
        resource.write('{"config": "{\\"sample\\": \\"wafer-1\\"}"}')
    with entry.resource("metadata.json", "metadata", "w") as resource:
        resource.write('{"created_at": 100.0}')
    with entry.resource("ellipsometry.json", "Elllipsometry data", "w") as resource:
        resource.write(
            '{"exposed_area_thickness_nm": [80.0, 100.0], '
            '"blank_area_thickness_nm": [200.0], "goodness_of_fit": [0.9, 0.8, 0.7]}'
        )


def _create_settings_presets(library: Library) -> None:
    entry = library.create_entry("Settings Presets", "Fixture")
    entry.add_tag("settings_presets")
    for name, resource_type, values in (
        ("sample_types.dat", "Sample Types", ("resist-a", "resist-b")),
        ("zr_filters.dat", "Zr Filters", ("100 nm", "200 nm")),
        ("operators.dat", "Operators", ("operator-b", "operator-c")),
    ):
        with entry.resource(name, resource_type, "w") as resource:
            resource.write("\n".join(values) + "\n")


def test_experiment_routes_return_numbered_read_only_results(tmp_path: Path) -> None:
    library = Library(str(tmp_path))
    run_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    for index, run_id in enumerate(run_ids):
        _create_run(library, run_id, index)
    _create_settings_presets(library)
    library.close()

    app = create_app(
        ApiSettings(data_path=str(tmp_path), trusted_hosts="testserver", docs_enabled=False, _env_file=None),
        source=FakeSource(),
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/experiments",
            params={"page_size": 25, "min_runtime": 2, "max_actual_dose": 2},
        )
        options = client.get("/api/v1/experiments/options")
        detail = client.get(f"/api/v1/experiments/{run_ids[1]}")
        resources = client.get(f"/api/v1/experiments/{run_ids[1]}/resources")
        metrics = client.get(f"/api/v1/experiments/{run_ids[1]}/metrics")
        download = client.get(
            f"/api/v1/experiments/{run_ids[1]}/resources/run.json",
            headers={"Range": "bytes=0-8"},
        )
        blocked_download = client.get(f"/api/v1/experiments/{run_ids[1]}/resources/not-registered.txt")
        missing = client.get(f"/api/v1/experiments/{uuid.uuid4()}")

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 2
    assert body["total_pages"] == 1
    assert all(item["runtime"] >= 2 for item in body["items"])
    assert options.status_code == 200
    assert options.json()["samples"] == ["resist-a", "resist-b"]
    assert options.json()["zr_filters"] == ["100 nm", "200 nm"]
    assert options.json()["operators"] == ["operator-b", "operator-c"]
    assert options.json()["actual_dose_min"] == 0.0
    assert options.json()["actual_dose_max"] == 2.0
    assert detail.status_code == 200
    assert detail.json()["settings"] == {"sample": "wafer-1"}
    assert resources.status_code == 200
    assert {item["name"] for item in resources.json()["items"]} == {
        "ellipsometry.json",
        "metadata.json",
        "run.json",
    }
    assert metrics.status_code == 200
    assert metrics.json()["exposed_average_nm"] == 90.0
    assert metrics.json()["blank_average_nm"] == 200.0
    assert metrics.json()["percent_development"] == pytest.approx(55.0)
    assert detail.json()["metrics"] == metrics.json()
    assert download.status_code == 206
    assert download.content == b'{"config"'
    assert download.headers["content-range"].startswith("bytes 0-8/")
    assert blocked_download.status_code == 404
    assert missing.status_code == 404


def test_experiment_routes_validate_page_and_filter_ranges(tmp_path: Path) -> None:
    app = create_app(
        ApiSettings(data_path=str(tmp_path), trusted_hosts="testserver", docs_enabled=False, _env_file=None),
        source=FakeSource(),
    )
    with TestClient(app) as client:
        invalid_size = client.get("/api/v1/experiments", params={"page_size": 10})
        invalid_range = client.get("/api/v1/experiments", params={"min_runtime": 3, "max_runtime": 2})

    assert invalid_size.status_code == 422
    assert invalid_range.status_code == 422


def test_exposure_events_route_returns_historical_empty_and_journaled_timelines(tmp_path: Path) -> None:
    from ipi_ecs.subsystems.run_events import STREAM_END_KIND, STREAM_START_KIND, RunEventStream, append_run_event

    library = Library(str(tmp_path))
    historical_id = uuid.uuid4()
    journaled_id = uuid.uuid4()
    _create_run(library, historical_id, 0)
    entry = library.create_entry("Journaled", "Fixture")
    entry.set_tag("experiment", "exposure")
    entry.set_tag("run", journaled_id.hex)
    stream = RunEventStream(journaled_id, uuid.uuid4(), "controller.lifecycle", uuid.uuid4())
    append_run_event(entry, stream.event(STREAM_START_KIND, producer_unix_ns=10, ingest_unix_ns=10))
    append_run_event(entry, stream.event("lifecycle.phase", {"phase": "PREINIT"}, producer_unix_ns=20, ingest_unix_ns=20))
    append_run_event(entry, stream.event(STREAM_END_KIND, producer_unix_ns=30, ingest_unix_ns=30))
    library.close()

    app = create_app(
        ApiSettings(data_path=str(tmp_path), trusted_hosts="testserver", docs_enabled=False, _env_file=None),
        source=FakeSource(),
    )
    with TestClient(app) as client:
        historical = client.get(f"/api/v1/experiments/{historical_id}/events")
        journaled = client.get(f"/api/v1/experiments/{journaled_id}/events")

    assert historical.status_code == 200
    assert historical.json() == {
        "schema_version": "1",
        "run_id": str(historical_id),
        "events": [],
        "complete": True,
        "issues": [],
        "wall_time_origin_unix_ns": None,
    }
    assert journaled.status_code == 200
    assert journaled.json()["complete"] is True
    assert journaled.json()["wall_time_origin_unix_ns"] == 20
    assert [event["kind"] for event in journaled.json()["events"]] == [
        "stream.start",
        "lifecycle.phase",
        "stream.end",
    ]


def test_observer_dose_series_route_preserves_source_algorithm_and_completeness(tmp_path: Path) -> None:
    from ipi_webview.experiments.models import (
        ObserverDoseComparison,
        ObserverDoseCompleteness,
        ObserverDosePoint,
        ObserverDoseSeries,
    )

    run_id = uuid.uuid4()
    session_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    completeness = ObserverDoseCompleteness(2, 2, 0, 1, 1)
    points = (
        ObserverDosePoint(0.0, 0.0, 0.0, None, 0),
        ObserverDosePoint(1.5, 0.25, 0.25, 249, 250),
    )
    comparison = ObserverDoseComparison(
        run_id,
        "complete",
        (
            ObserverDoseSeries(
                session_id,
                "siglent",
                "scope-1",
                "captured",
                "siglent-captured-v1-native-integral-sum",
                "complete",
                points,
                250,
                250,
                2,
                0.25,
                0.001,
                profile_id,
                3,
                "Siglent calibration",
                "a" * 64,
                ObserverDoseCompleteness(2, 2, 0, 0, 0),
                (),
            ),
            ObserverDoseSeries(
                session_id,
                "siglent",
                "scope-1",
                "legacy_compensated",
                "legacy-siglent-v1-sequence-gap-compensation",
                "incomplete",
                points,
                2,
                500,
                2,
                2.5,
                0.001,
                profile_id,
                1,
                "Legacy Siglent Dose Calibration",
                "b" * 64,
                completeness,
                ("One transfer lacks timing context.",),
            ),
        ),
        (),
        "full",
        "run_preinit",
    )

    class _Repository:
        def start(self) -> None:
            pass

        def close(self) -> None:
            pass

        def get_observer_dose_comparison(self, requested_run_id, *, resolution):
            assert requested_run_id == run_id
            assert resolution == "full"
            return comparison

    app = create_app(
        ApiSettings(data_path=str(tmp_path), trusted_hosts="testserver", docs_enabled=False, _env_file=None),
        source=FakeSource(),
        experiment_repository=_Repository(),
    )
    with TestClient(app) as client:
        response = client.get(f"/api/v1/experiments/{run_id}/observer-dose-series")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "1"
    assert body["wall_origin_quality"] == "run_preinit"
    assert [series["algorithm"] for series in body["series"]] == ["captured", "legacy_compensated"]
    assert body["series"][0]["calibration_profile_id"] == str(profile_id)
    assert body["series"][0]["total_dose_mj_cm2"] == 0.25
    assert body["series"][1]["status"] == "incomplete"
    assert body["series"][1]["completeness"] == {
        "snapshot_count": 2,
        "included_snapshot_count": 2,
        "excluded_snapshot_count": 0,
        "unknown_eligibility_snapshot_count": 1,
        "unknown_step_mode_snapshot_count": 1,
    }


def test_snapshot_analysis_route_backfills_registered_metadata(tmp_path: Path) -> None:
    run_uuid = uuid.uuid4()
    snapshot_uuid = uuid.uuid4()
    pulse = np.concatenate((np.zeros(25), np.full(15, 3.0)))
    data = np.column_stack((np.arange(80, dtype=float) * 1e-9, np.tile(pulse, 2)))
    indexes = np.array([[0, 10.0], [40, 20.0]])
    library = Library(str(tmp_path))
    entry = library.create_entry("Snapshot", "Fixture")
    entry.set_tag("experiment", "exposure")
    entry.set_tag("run", run_uuid.hex)
    with entry.resource(f"snap_{snapshot_uuid}.npz", "snapshot", "wb") as resource:
        np.savez(resource, data=data, indexes=indexes)
    with entry.resource(f"snap_{snapshot_uuid}.json", "snap_meta", "w") as resource:
        json.dump({"start": 0, "end": 1_000_000_000}, resource)
    library.close()

    app = create_app(
        ApiSettings(data_path=str(tmp_path), trusted_hosts="testserver", docs_enabled=False, _env_file=None),
        source=FakeSource(),
    )
    with TestClient(app) as client:
        response = client.get(f"/api/v1/experiments/{run_uuid}/snapshots/{snapshot_uuid}/analysis")
        voltage = client.get(f"/api/v1/experiments/{run_uuid}/snapshots/{snapshot_uuid}/series/voltage")
        apparent_voltage = client.get(
            f"/api/v1/experiments/{run_uuid}/snapshots/{snapshot_uuid}/series/voltage",
            params={"time_mode": "apparent"},
        )
        peaks = client.get(
            f"/api/v1/experiments/{run_uuid}/snapshots/{snapshot_uuid}/series/peaks",
            params={"rolling_window": 10},
        )
        run_series = client.get(f"/api/v1/experiments/{run_uuid}/dose-series")

    assert response.status_code == 200
    assert response.json()["schema_version"] == "1"
    assert response.json()["metadata_backfilled"] is True
    assert response.json()["backfill_error"] is None
    assert response.json()["step_mode_source"] == "inferred"
    assert response.json()["is_step_exposure"] is False
    assert response.json()["runtime_contribution_seconds"] == pytest.approx(1.0)
    assert voltage.status_code == 200
    assert voltage.json()["point_count"] == 80
    assert voltage.json()["x"][0] == 0.0
    assert apparent_voltage.status_code == 200
    assert apparent_voltage.json()["point_count"] == voltage.json()["point_count"]
    assert apparent_voltage.json()["x_label"] == "Apparent time (s)"
    assert all(left <= right for left, right in zip(apparent_voltage.json()["x"], apparent_voltage.json()["x"][1:]))
    assert apparent_voltage.json()["x"][-1] < voltage.json()["x"][-1]
    assert peaks.status_code == 200
    assert peaks.json()["rolling_window"] == 10
    assert len(peaks.json()["y"]) == 2
    assert run_series.status_code == 200
    assert run_series.json()["schema_version"] == "3"
    assert run_series.json()["status"] == "missing"
    assert run_series.json()["points"] == []


def test_native_hdf5_snapshot_routes_do_not_require_legacy_metadata(tmp_path: Path) -> None:
    from chamber_ctl.data.calibration import CalibrationProfile
    from euv_acquisition.analysis import analyze_pulse
    from euv_acquisition.models import CaptureConfig, CapturedPulse, PulseRecord, SnapshotCloseReason
    from euv_acquisition.snapshot import SnapshotStore

    run_uuid = uuid.uuid4()
    session_id = uuid.uuid4()
    profile = CalibrationProfile(
        profile_id=uuid.uuid4(),
        revision=1,
        name="Fixture profile",
        created_at=1.0,
        algorithm_version="dose-v1",
        signal_polarity=1,
        load_resistance_ohms=50.0,
        photodiode_responsivity_a_per_w=0.14,
        illuminated_area_cm2=0.05,
    )
    config = CaptureConfig(sample_rate_hz=1_000_000.0, window_seconds=4e-6, pretrigger_seconds=1e-6)
    store = SnapshotStore(tmp_path / "source")
    samples = np.asarray([0.0, 0.2, 0.2, 0.0], dtype=np.float32)
    manifest = store.write(
        [PulseRecord(session_id, 0, CapturedPulse(samples, 1_000_000_000, 0), analyze_pulse(samples, config))],
        config,
        SnapshotCloseReason.CAPTURE_STOP,
        source_kind="simulated",
        source_id="test",
    )
    library = Library(str(tmp_path))
    entry = library.create_entry("Native snapshot", "Fixture")
    entry.set_tag("experiment", "exposure")
    entry.set_tag("run", run_uuid.hex)
    with entry.resource("euv_calibration_profile.json", "euv_calibration_profile", "w") as resource:
        json.dump(profile.to_dict(), resource)
    with entry.resource(manifest.filename, "euv_snapshot", "wb") as resource:
        resource.write(store.path_for(manifest).read_bytes())
    with entry.resource("end_metadata.json", "metadata", "w") as resource:
        json.dump({"outcome": "STOPPED"}, resource)
    library.close()

    app = create_app(
        ApiSettings(data_path=str(tmp_path), trusted_hosts="testserver", docs_enabled=False, _env_file=None),
        source=FakeSource(),
    )
    with TestClient(app) as client:
        detail = client.get(f"/api/v1/experiments/{run_uuid}")
        analysis = client.get(f"/api/v1/experiments/{run_uuid}/snapshots/{manifest.snapshot_id}/analysis")
        voltage = client.get(f"/api/v1/experiments/{run_uuid}/snapshots/{manifest.snapshot_id}/series/voltage")
        download = client.get(f"/api/v1/experiments/{run_uuid}/resources/{manifest.filename}")
        missing_graph = client.get(f"/api/v1/experiments/{run_uuid}/dose-series")
        repaired_graph = client.post(f"/api/v1/experiments/{run_uuid}/dose-series/ensure")
        thumbnail_graph = client.get(f"/api/v1/experiments/{run_uuid}/dose-series", params={"resolution": "thumbnail"})

    assert detail.status_code == 200
    snapshot = detail.json()["snapshots"][0]
    assert snapshot["format"] == "euv_hdf5"
    assert snapshot["metadata"] is None
    assert analysis.status_code == 200
    assert analysis.json()["step_mode_source"] == "native"
    assert analysis.json()["metadata_backfilled"] is False
    assert voltage.status_code == 200
    assert voltage.json()["point_count"] == len(samples)
    assert download.status_code == 200
    assert download.content == store.path_for(manifest).read_bytes()
    assert missing_graph.json()["status"] == "missing"
    assert repaired_graph.status_code == 200
    assert repaired_graph.json()["status"] == "complete"
    assert repaired_graph.json()["source"] == "persisted"
    assert repaired_graph.json()["points"][-1]["cumulative_dose_mj_cm2"] > 0
    assert thumbnail_graph.json()["points"][-1]["cumulative_dose_mj_cm2"] == pytest.approx(
        repaired_graph.json()["points"][-1]["cumulative_dose_mj_cm2"]
    )


def test_detail_degrades_when_registered_optional_resource_is_unavailable(tmp_path: Path) -> None:
    run_uuid = uuid.uuid4()
    library = Library(str(tmp_path))
    _create_run(library, run_uuid, 1)
    entry = library.query({"tags": {"run": run_uuid.hex}}, limit=1)[0]
    (tmp_path / entry.get_foldername() / "ellipsometry.json").unlink()
    library.close()

    app = create_app(
        ApiSettings(
            data_path=str(tmp_path),
            experiment_resource_retry_attempts=2,
            experiment_resource_retry_delay=0,
            trusted_hosts="testserver",
            docs_enabled=False,
            _env_file=None,
        ),
        source=FakeSource(),
    )
    with TestClient(app) as client:
        detail = client.get(f"/api/v1/experiments/{run_uuid}")
        download = client.get(f"/api/v1/experiments/{run_uuid}/resources/ellipsometry.json")
        export = client.get(f"/api/v1/experiments/{run_uuid}/export")

    assert detail.status_code == 200
    body = detail.json()
    resource = next(item for item in body["resources"] if item["name"] == "ellipsometry.json")
    assert resource["available"] is False
    assert resource["downloadable"] is False
    assert resource["size_bytes"] is None
    assert body["metrics"]["degraded"] is True
    assert any(issue["resource_name"] == "ellipsometry.json" for issue in body["issues"])
    assert download.status_code == 503
    assert export.status_code == 200
    assert export.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
        names = set(archive.namelist())
        root = str(run_uuid)
        assert f"{root}/resources/run.json" in names
        assert f"{root}/resources/metadata.json" in names
        assert f"{root}/resources/ellipsometry.json" not in names
        manifest = json.loads(archive.read(f"{root}/manifest.json"))
        assert "run.json" in manifest["exported_resources"]
        assert any("ellipsometry.json" in error for error in manifest["errors"])