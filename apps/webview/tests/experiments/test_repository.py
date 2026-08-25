from __future__ import annotations

import threading
import time
import uuid
import json
from pathlib import Path

import numpy as np
import pytest

import ipi_ecs.db.db_library as db_library
import ipi_webview.experiments.repository as repository_module
from ipi_ecs.db.db_library import Library
from ipi_webview.experiments.models import ExperimentBrowserConfig, ExperimentFilters
from ipi_webview.experiments.repository import (
    ExperimentBrowserRepository,
    ExperimentIntegrityError,
    ExperimentRepositoryUnavailable,
)
from ipi_webview.experiments.waveforms import SnapshotResourceUnavailable, analyze_registered_snapshot


def _create_run(library: Library, index: int, *, experiment: str = "exposure") -> None:
    entry = library.create_entry(f"Run {index}", f"Description {index}")
    entry.set_tag("experiment", experiment)
    entry.set_tag("run", uuid.uuid4().hex)
    entry.set_tag("dose", float(index))
    entry.set_tag("target_dose", float(index + 10))
    entry.set_tag("runtime", float(index + 1))
    entry.set_tag("sample", f"sample-{index % 2}")
    entry.set_tag("operator", "operator-a")
    entry.set_tag("zr_filter", "200 nm")


def _create_settings_presets(library: Library) -> None:
    entry = library.create_entry("Settings Presets", "Fixture")
    entry.add_tag("settings_presets")
    for name, resource_type, values in (
        ("sample_types.dat", "Sample Types", ("sample-a", "sample-b")),
        ("zr_filters.dat", "Zr Filters", ("100 nm", "200 nm")),
        ("operators.dat", "Operators", ("operator-b", "operator-c")),
    ):
        with entry.resource(name, resource_type, "w") as resource:
            resource.write("\n".join(values) + "\n")


def test_list_page_is_read_only_scoped_and_uses_indexed_runtime_filters(tmp_path: Path) -> None:
    library = Library(str(tmp_path))
    for index in range(5):
        _create_run(library, index)
    _create_run(library, 99, experiment="calibration")
    library.close()

    repository = ExperimentBrowserRepository(
        ExperimentBrowserConfig(str(tmp_path), default_page_size=2, allowed_page_sizes=(2, 4))
    )
    repository.start()
    try:
        page = repository.list_page(ExperimentFilters(min_runtime=3.0), page=1, page_size=2)
        next_page = repository.list_page(ExperimentFilters(min_runtime=3.0), page=2, page_size=2)
    finally:
        repository.close()

    assert page.total_count == 3
    assert page.total_pages == 2
    assert len(page.items) == 2
    assert all(item.runtime is not None and item.runtime >= 3.0 for item in page.items)
    assert all(item.effective_dose_rate is not None for item in page.items)
    assert len(next_page.items) == 1
    assert {item.name for item in (*page.items, *next_page.items)} == {"Run 2", "Run 3", "Run 4"}


def test_filter_options_and_complete_numeric_ranges_are_indexed(tmp_path: Path) -> None:
    library = Library(str(tmp_path))
    for index in range(5):
        _create_run(library, index)
    _create_settings_presets(library)
    library.close()

    repository = ExperimentBrowserRepository(ExperimentBrowserConfig(str(tmp_path)))
    repository.start()
    try:
        options = repository.get_filter_options()
        page = repository.list_page(
            ExperimentFilters(
                min_actual_dose=1.0,
                max_actual_dose=3.0,
                min_target_dose=11.0,
                max_target_dose=13.0,
                min_runtime=2.0,
                max_runtime=4.0,
            )
        )
    finally:
        repository.close()

    assert options.samples == ("sample-a", "sample-b")
    assert options.operators == ("operator-b", "operator-c")
    assert options.zr_filters == ("100 nm", "200 nm")
    assert (options.actual_dose_min, options.actual_dose_max) == (0.0, 4.0)
    assert (options.target_dose_min, options.target_dose_max) == (10.0, 14.0)
    assert (options.runtime_min, options.runtime_max) == (1.0, 5.0)
    assert {item.name for item in page.items} == {"Run 1", "Run 2", "Run 3"}


def test_repository_owns_reader_thread_and_reopens_after_store_failure() -> None:
    run_uuid = uuid.uuid4()
    calls: list[tuple[str, int]] = []

    class FakeEntry:
        def get_name(self):
            return "Run"

        def get_description(self):
            return "Fixture"

        def get_timestamp(self):
            return 10.0

        def get_tags(self):
            return {"experiment": "exposure", "run": run_uuid.hex, "runtime": "2", "dose": "4"}

    class FakeRecord:
        def get_record(self):
            return FakeEntry()

    class FakeReader:
        def __init__(self, fail: bool) -> None:
            self.fail = fail
            self.closed = False

        def count(self, _query):
            calls.append(("count", threading.get_ident()))
            if self.fail:
                raise OSError("NAS unavailable")
            return 1

        def query(self, _query, limit=None, *, offset=0, cursor=None):
            calls.append(("query", threading.get_ident()))
            return [FakeRecord()]

        def close(self):
            self.closed = True
            calls.append(("close", threading.get_ident()))

    readers = [FakeReader(fail=True), FakeReader(fail=False)]

    def factory(*_args, **_kwargs):
        calls.append(("open", threading.get_ident()))
        return readers.pop(0)

    repository = ExperimentBrowserRepository(
        ExperimentBrowserConfig("C:/fixtures", default_page_size=25),
        reader_factory=factory,
    )
    repository.start()
    try:
        with pytest.raises(ExperimentRepositoryUnavailable, match="temporarily unavailable"):
            repository.list_page()
        page = repository.list_page()
    finally:
        repository.close()

    worker_threads = {thread_id for _action, thread_id in calls}
    assert page.total_count == 1
    assert len(worker_threads) == 1
    assert readers == []


def test_detail_uses_registered_resources_and_reports_unpaired_snapshots(tmp_path: Path) -> None:
    run_uuid = uuid.uuid4()
    snapshot_uuid = uuid.uuid4()
    library = Library(str(tmp_path))
    entry = library.create_entry("Run", "Fixture")
    entry.set_tag("experiment", "exposure")
    entry.set_tag("run", run_uuid.hex)
    with entry.resource("run.json", "run_state", "w") as resource:
        resource.write('{"config": "{\\"operator\\": \\"A\\"}"}')
    with entry.resource("metadata.json", "metadata", "w") as resource:
        resource.write('{"event_uuid": "event-1", "created_at": 10.0}')
    with entry.resource(f"snap_{snapshot_uuid}.npz", "snapshot", "wb") as resource:
        resource.write(b"waveform")
    with entry.resource(f"snap_{snapshot_uuid}.json", "snap_meta", "w") as resource:
        resource.write("{}")
    folder = tmp_path / entry.get_foldername()
    (folder / "unregistered.txt").write_text("hidden", encoding="utf-8")
    library.close()

    repository = ExperimentBrowserRepository(ExperimentBrowserConfig(str(tmp_path)))
    repository.start()
    try:
        detail = repository.get_detail(run_uuid)
    finally:
        repository.close()

    assert detail.settings == {"operator": "A"}
    assert detail.log_range.event_id == "event-1"
    assert {resource.name for resource in detail.resources} == {
        "metadata.json",
        "run.json",
        f"snap_{snapshot_uuid}.json",
        f"snap_{snapshot_uuid}.npz",
    }
    assert detail.snapshots[0].snapshot_id == snapshot_uuid

    library = Library(str(tmp_path))
    invalid_entry = library.create_entry("Invalid", "Fixture")
    invalid_run_uuid = uuid.uuid4()
    invalid_snapshot_uuid = uuid.uuid4()
    invalid_entry.set_tag("experiment", "exposure")
    invalid_entry.set_tag("run", invalid_run_uuid.hex)
    with invalid_entry.resource(f"snap_{invalid_snapshot_uuid}.npz", "snapshot", "wb") as resource:
        resource.write(b"unpaired")
    library.close()

    repository = ExperimentBrowserRepository(ExperimentBrowserConfig(str(tmp_path)))
    repository.start()
    try:
        invalid_detail = repository.get_detail(invalid_run_uuid)
        with pytest.raises(ExperimentIntegrityError, match="missing its registered metadata pair"):
            repository.get_snapshot_analysis(invalid_run_uuid, invalid_snapshot_uuid)
    finally:
        repository.close()

    assert invalid_detail.snapshots == ()
    assert any(issue.section == "snapshots" and issue.kind == "integrity" for issue in invalid_detail.issues)


def test_metrics_support_row_format_and_degrade_malformed_data(tmp_path: Path) -> None:
    library = Library(str(tmp_path))
    run_uuid = uuid.uuid4()
    entry = library.create_entry("Metrics", "Fixture")
    entry.set_tag("experiment", "exposure")
    entry.set_tag("run", run_uuid.hex)
    with entry.resource("ellipsometry.json", "metrics", "w") as resource:
        resource.write(
            '{"measurements": ['
            '{"spot_type": "EXPOSED", "thickness_nm": 50.0, "goodness_of_fit": 0.9}, '
            '{"spot_type": "blank", "thickness_nm": 100.0, "goodness_of_fit": 0.8}]}'
        )
    library.close()

    repository = ExperimentBrowserRepository(ExperimentBrowserConfig(str(tmp_path)))
    repository.start()
    try:
        metrics = repository.get_metrics(run_uuid)
    finally:
        repository.close()

    assert [measurement.spot_type for measurement in metrics.measurements] == ["exposed", "blank"]
    assert metrics.percent_development == pytest.approx(50.0)
    assert metrics.degraded is False

    library = Library(str(tmp_path))
    invalid_run_uuid = uuid.uuid4()
    invalid = library.create_entry("Broken metrics", "Fixture")
    invalid.set_tag("experiment", "exposure")
    invalid.set_tag("run", invalid_run_uuid.hex)
    with invalid.resource("ellipsometry.json", "metrics", "w") as resource:
        resource.write("[]")
    library.close()

    repository = ExperimentBrowserRepository(ExperimentBrowserConfig(str(tmp_path)))
    repository.start()
    try:
        degraded = repository.get_metrics(invalid_run_uuid)
    finally:
        repository.close()

    assert degraded.measurements == ()
    assert degraded.degraded is True
    assert degraded.error is not None


def test_snapshot_analysis_uses_only_a_registered_pair_and_backfills_metadata(tmp_path: Path) -> None:
    run_uuid = uuid.uuid4()
    snapshot_uuid = uuid.uuid4()
    points_per_pulse = 40
    pulse = np.concatenate((np.zeros(25), np.full(points_per_pulse - 25, 3.0)))
    data = np.column_stack((np.arange(80, dtype=float) * 1e-9, np.tile(pulse, 2)))
    indexes = np.array([[0, 10.0], [40, 20.0]])
    library = Library(str(tmp_path))
    entry = library.create_entry("Waveform", "Fixture")
    entry.set_tag("experiment", "exposure")
    entry.set_tag("run", run_uuid.hex)
    with entry.resource(f"snap_{snapshot_uuid}.npz", "snapshot", "wb") as resource:
        np.savez(resource, data=data, indexes=indexes)
    with entry.resource(f"snap_{snapshot_uuid}.json", "snap_meta", "w") as resource:
        json.dump({"start": 0, "end": 1_000_000_000}, resource)
    library.close()

    repository = ExperimentBrowserRepository(ExperimentBrowserConfig(str(tmp_path)))
    repository.start()
    try:
        analysis = repository.get_snapshot_analysis(run_uuid, snapshot_uuid)
        voltage = repository.get_snapshot_series(run_uuid, snapshot_uuid, "voltage")
        peaks = repository.get_snapshot_series(run_uuid, snapshot_uuid, "peaks", rolling_window=10)
        pulse_dose = repository.get_snapshot_series(run_uuid, snapshot_uuid, "dose", rolling_window=10)
    finally:
        repository.close()

    assert analysis.metadata_backfilled is True
    assert analysis.step_mode_source == "inferred"
    assert analysis.total_dose_mj_cm2 == pytest.approx(0.012428571428571428)
    folder = tmp_path / entry.get_foldername()
    metadata = json.loads((folder / f"snap_{snapshot_uuid}.json").read_text(encoding="utf-8"))
    assert metadata["dose"] == pytest.approx(analysis.total_dose_mj_cm2)
    assert metadata["is_step_exposure"] is False
    assert voltage.point_count == 80
    assert voltage.x[0] == 0.0
    assert voltage.y[-1] == 3.0
    assert peaks.x == (0.0, 10.0)
    assert peaks.y == pytest.approx((3.0, 3.0))
    assert pulse_dose.x == (1.0, 2.0)
    assert len(pulse_dose.y) == 2


def test_hdf5_snapshot_is_complete_without_legacy_metadata_and_uses_calibration_provenance(tmp_path: Path) -> None:
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
    source_store = SnapshotStore(tmp_path / "source")
    samples = (
        np.asarray([0.0, 0.2, 0.2, 0.0], dtype=np.float32),
        np.asarray([0.0, 0.3, 0.3, 0.0], dtype=np.float32),
    )
    manifest = source_store.write(
        [
            PulseRecord(session_id, index, CapturedPulse(pulse, 1_000_000_000 + index * 10_000_000, index), analyze_pulse(pulse, config))
            for index, pulse in enumerate(samples)
        ],
        config,
        SnapshotCloseReason.CAPTURE_STOP,
        source_kind="simulated",
        source_id="test",
    )
    library = Library(str(tmp_path))
    entry = library.create_entry("Native snapshot", "Fixture")
    entry.set_tag("experiment", "exposure")
    entry.set_tag("run", run_uuid.hex)
    from ipi_ecs.subsystems.run_events import STREAM_END_KIND, STREAM_START_KIND, RunEventStream, append_run_event

    lifecycle = RunEventStream(run_uuid, uuid.uuid4(), "controller.lifecycle", uuid.uuid4())
    timing = RunEventStream(run_uuid, uuid.uuid4(), "acquisition.timing", uuid.uuid4())
    append_run_event(entry, lifecycle.event(STREAM_START_KIND, producer_unix_ns=980_000_000, ingest_unix_ns=980_000_000))
    append_run_event(entry, lifecycle.event("lifecycle.phase", {"phase": "CAN_START"}, producer_unix_ns=985_000_000, ingest_unix_ns=985_000_000))
    append_run_event(entry, lifecycle.event("lifecycle.phase", {"phase": "PREINIT"}, producer_unix_ns=990_000_000, ingest_unix_ns=990_000_000))
    append_run_event(entry, lifecycle.event("lifecycle.phase", {"phase": "STOPPED", "outcome": "STOPPED"}, producer_unix_ns=1_020_000_000, ingest_unix_ns=1_020_000_000))
    append_run_event(entry, lifecycle.event(STREAM_END_KIND, producer_unix_ns=1_020_000_000, ingest_unix_ns=1_020_000_000))
    append_run_event(entry, timing.event(STREAM_START_KIND, producer_unix_ns=995_000_000, ingest_unix_ns=995_000_000))
    append_run_event(
        entry,
        timing.event(
            "timing.euv_transmitting",
            {"value": True},
            producer_unix_ns=995_000_000,
            ingest_unix_ns=995_000_000,
            runtime_seconds=0.0,
        ),
    )
    append_run_event(
        entry,
        timing.event(
            "timing.euv_transmitting",
            {"value": False},
            producer_unix_ns=1_005_000_000,
            ingest_unix_ns=1_005_000_000,
            runtime_seconds=0.01,
        ),
    )
    append_run_event(entry, timing.event(STREAM_END_KIND, producer_unix_ns=1_020_000_000, ingest_unix_ns=1_020_000_000))
    with entry.resource("euv_calibration_profile.json", "euv_calibration_profile", "w") as resource:
        json.dump(profile.to_dict(), resource)
    with entry.resource(manifest.filename, "euv_snapshot", "wb") as resource:
        resource.write(source_store.path_for(manifest).read_bytes())
    with entry.resource("euv_capture_timeline.json", "euv_capture_timeline", "w") as resource:
        json.dump(
            {
                "schema_version": 1,
                "snapshots": [
                    {
                        "snapshot_id": str(manifest.snapshot_id),
                        "final_sequence": manifest.final_sequence,
                        "cumulative_dose_mj_cm2": 0.0,
                        "cumulative_runtime_seconds": 0.25,
                    }
                ],
            },
            resource,
        )
    with entry.resource("end_metadata.json", "metadata", "w") as resource:
        json.dump({"outcome": "STOPPED"}, resource)
    library.close()

    repository = ExperimentBrowserRepository(ExperimentBrowserConfig(str(tmp_path)))
    repository.start()
    try:
        detail = repository.get_detail(run_uuid)
        analysis = repository.get_snapshot_analysis(run_uuid, manifest.snapshot_id)
        voltage = repository.get_snapshot_series(run_uuid, manifest.snapshot_id, "voltage")
        peaks = repository.get_snapshot_series(run_uuid, manifest.snapshot_id, "peaks")
        dose = repository.get_snapshot_series(run_uuid, manifest.snapshot_id, "dose")
        missing_series = repository.get_run_dose_series(run_uuid)
        run_series = repository.ensure_run_dose_series(run_uuid)
        events = repository.get_event_timeline(run_uuid)
        thumbnail_series = repository.get_run_dose_series(run_uuid, resolution="thumbnail")
        wall_series = repository.get_run_dose_series(run_uuid, time_mode="wall")
    finally:
        repository.close()

    assert detail.snapshots[0].snapshot_id == manifest.snapshot_id
    assert detail.snapshots[0].snapshot_format == "euv_hdf5"
    assert detail.snapshots[0].metadata is None
    assert analysis.total_dose_mj_cm2 > 0
    assert analysis.metadata_backfilled is False
    assert analysis.step_mode_source == "native"
    assert voltage.point_count == 8
    assert peaks.point_count == 2
    assert dose.point_count == 2
    assert missing_series.status == "missing"
    assert run_series.status == "complete"
    assert run_series.source == "persisted"
    assert run_series.points[-1].runtime_seconds == pytest.approx(0.25)
    assert run_series.points[-1].cumulative_dose_mj_cm2 == pytest.approx(analysis.total_dose_mj_cm2)
    assert thumbnail_series.points[-1].cumulative_dose_mj_cm2 == pytest.approx(
        run_series.points[-1].cumulative_dose_mj_cm2
    )
    assert events.complete is True
    assert events.wall_time_origin_unix_ns == 990_000_000
    assert len(events.events) == 9
    transmitting = [annotation for annotation in dose.annotations if annotation.category == "transmitting"]
    assert len(transmitting) == 2
    assert transmitting[0].x == 1.0
    assert transmitting[0].x_end == 2.0
    assert transmitting[0].projection_quality == "next_pulse"
    assert wall_series.points[-1].wall_elapsed_seconds == pytest.approx(0.02)
    assert any(annotation.label == "PREINIT" and annotation.x == 0.0 for annotation in wall_series.annotations)


def test_slow_snapshot_analysis_does_not_block_index_queries(tmp_path: Path) -> None:
    run_uuid = uuid.uuid4()
    snapshot_uuid = uuid.uuid4()
    pulse = np.concatenate((np.zeros(25), np.full(15, 3.0)))
    data = np.column_stack((np.arange(80, dtype=float) * 1e-9, np.tile(pulse, 2)))
    indexes = np.array([[0, 10.0], [40, 20.0]])
    library = Library(str(tmp_path))
    entry = library.create_entry("Waveform", "Fixture")
    entry.set_tag("experiment", "exposure")
    entry.set_tag("run", run_uuid.hex)
    with entry.resource(f"snap_{snapshot_uuid}.npz", "snapshot", "wb") as resource:
        np.savez(resource, data=data, indexes=indexes)
    with entry.resource(f"snap_{snapshot_uuid}.json", "snap_meta", "w") as resource:
        json.dump({"start": 0, "end": 1_000_000_000}, resource)
    library.close()

    analysis_started = threading.Event()
    release_analysis = threading.Event()

    def slow_analyzer(waveform_path: Path, metadata_path: Path):
        analysis_started.set()
        if not release_analysis.wait(timeout=2.0):
            raise TimeoutError("Test did not release snapshot analysis.")
        return analyze_registered_snapshot(waveform_path, metadata_path)

    repository = ExperimentBrowserRepository(
        ExperimentBrowserConfig(str(tmp_path)),
        snapshot_analyzer=slow_analyzer,
    )
    repository.start()
    analysis_thread = threading.Thread(
        target=repository.get_snapshot_analysis,
        args=(run_uuid, snapshot_uuid),
    )
    analysis_thread.start()
    assert analysis_started.wait(timeout=1.0)

    page_result = {}
    page_finished = threading.Event()

    def read_page() -> None:
        page_result["page"] = repository.list_page()
        page_finished.set()

    page_thread = threading.Thread(target=read_page)
    page_thread.start()
    completed_while_analysis_blocked = page_finished.wait(timeout=0.5)
    release_analysis.set()
    analysis_thread.join(timeout=2.0)
    page_thread.join(timeout=2.0)
    repository.close()

    assert completed_while_analysis_blocked is True
    assert page_result["page"].total_count == 1


def test_detail_salvages_available_data_when_optional_resource_is_unavailable(tmp_path: Path) -> None:
    run_uuid = uuid.uuid4()
    library = Library(str(tmp_path))
    entry = library.create_entry("Deferred metrics", "Fixture")
    entry.set_tag("experiment", "exposure")
    entry.set_tag("run", run_uuid.hex)
    with entry.resource("run.json", "run_state", "w") as resource:
        resource.write('{"config": "{\\"operator\\": \\"A\\"}"}')
    with entry.resource("metadata.json", "metadata", "w") as resource:
        resource.write('{"created_at": 10.0}')
    with entry.resource("ellipsometry.json", "metrics", "w") as resource:
        resource.write("{}")
    (tmp_path / entry.get_foldername() / "ellipsometry.json").unlink()
    library.close()

    repository = ExperimentBrowserRepository(
        ExperimentBrowserConfig(
            str(tmp_path),
            resource_retry_attempts=2,
            resource_retry_delay=0.0,
        )
    )
    repository.start()
    try:
        detail = repository.get_detail(run_uuid)
    finally:
        repository.close()

    metrics_resource = next(resource for resource in detail.resources if resource.name == "ellipsometry.json")
    assert detail.settings == {"operator": "A"}
    assert metrics_resource.available is False
    assert metrics_resource.downloadable is False
    assert metrics_resource.size_bytes is None
    assert metrics_resource.error is not None
    assert detail.metrics.degraded is True
    assert "ellipsometry.json" in (detail.metrics.error or "")
    assert any(
        issue.resource_name == "ellipsometry.json" and issue.kind == "unavailable"
        for issue in detail.issues
    )


def test_resource_open_retries_transient_cloud_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_uuid = uuid.uuid4()
    library = Library(str(tmp_path))
    entry = library.create_entry("Cloud resource", "Fixture")
    entry.set_tag("experiment", "exposure")
    entry.set_tag("run", run_uuid.hex)
    with entry.resource("payload.bin", "data", "wb") as resource:
        resource.write(b"payload")
    library.close()

    real_open = Path.open
    attempts = 0

    def flaky_open(path: Path, *args, **kwargs):
        nonlocal attempts
        if path.name == "payload.bin":
            attempts += 1
            if attempts < 3:
                raise OSError("cloud provider temporarily unavailable")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky_open)
    repository = ExperimentBrowserRepository(
        ExperimentBrowserConfig(
            str(tmp_path),
            resource_retry_attempts=3,
            resource_retry_delay=0.0,
        )
    )
    repository.start()
    try:
        opened = repository.open_resource(run_uuid, "payload.bin")
        try:
            assert opened.file.read() == b"payload"
        finally:
            opened.close()
    finally:
        repository.close()

    assert attempts == 3


def test_snapshot_analysis_retries_transient_cloud_hydration(tmp_path: Path) -> None:
    run_uuid = uuid.uuid4()
    snapshot_uuid = uuid.uuid4()
    pulse = np.concatenate((np.zeros(25), np.full(15, 3.0)))
    data = np.column_stack((np.arange(80, dtype=float) * 1e-9, np.tile(pulse, 2)))
    indexes = np.array([[0, 10.0], [40, 20.0]])
    library = Library(str(tmp_path))
    entry = library.create_entry("Retry waveform", "Fixture")
    entry.set_tag("experiment", "exposure")
    entry.set_tag("run", run_uuid.hex)
    with entry.resource(f"snap_{snapshot_uuid}.npz", "snapshot", "wb") as resource:
        np.savez(resource, data=data, indexes=indexes)
    with entry.resource(f"snap_{snapshot_uuid}.json", "snap_meta", "w") as resource:
        json.dump({"start": 0, "end": 1_000_000_000}, resource)
    library.close()

    attempts = 0

    def flaky_analyzer(waveform_path: Path, metadata_path: Path):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise SnapshotResourceUnavailable("Box hydration failed")
        return analyze_registered_snapshot(waveform_path, metadata_path)

    repository = ExperimentBrowserRepository(
        ExperimentBrowserConfig(
            str(tmp_path),
            resource_retry_attempts=3,
            resource_retry_delay=0,
        ),
        snapshot_analyzer=flaky_analyzer,
    )
    repository.start()
    try:
        result = repository.get_snapshot_analysis(run_uuid, snapshot_uuid)
    finally:
        repository.close()

    assert attempts == 3
    assert result.total_dose_mj_cm2 > 0


def test_detail_salvages_indexed_data_when_core_json_is_malformed(tmp_path: Path) -> None:
    run_uuid = uuid.uuid4()
    library = Library(str(tmp_path))
    entry = library.create_entry("Malformed core data", "Fixture")
    entry.set_tag("experiment", "exposure")
    entry.set_tag("run", run_uuid.hex)
    with entry.resource("run.json", "run_state", "w") as resource:
        resource.write('{"config": "not-json"}')
    with entry.resource("metadata.json", "metadata", "w") as resource:
        resource.write("[]")
    library.close()

    repository = ExperimentBrowserRepository(
        ExperimentBrowserConfig(str(tmp_path), resource_retry_delay=0)
    )
    repository.start()
    try:
        detail = repository.get_detail(run_uuid)
    finally:
        repository.close()

    assert detail.summary.name == "Malformed core data"
    assert detail.settings == {}
    assert detail.metadata == {}
    assert {issue.resource_name for issue in detail.issues} == {"run.json", "metadata.json"}
    assert all(issue.kind == "malformed" for issue in detail.issues)


def test_detail_retries_transient_invalid_registry_reads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_uuid = uuid.uuid4()
    library = Library(str(tmp_path))
    entry = library.create_entry("Cold registry", "Fixture")
    entry.set_tag("experiment", "exposure")
    entry.set_tag("run", run_uuid.hex)
    with entry.resource("metadata.json", "metadata", "w") as resource:
        resource.write('{"created_at": 10.0}')
    target_entry_uuid = entry.get_uuid()
    library.close()

    real_list_resources = db_library.Entry.list_resources
    attempts = 0

    def flaky_list_resources(loaded_entry):
        nonlocal attempts
        if loaded_entry.get_uuid() == target_entry_uuid:
            attempts += 1
            if attempts < 3:
                raise ValueError("Invalid file")
        return real_list_resources(loaded_entry)

    monkeypatch.setattr(db_library.Entry, "list_resources", flaky_list_resources)
    repository = ExperimentBrowserRepository(
        ExperimentBrowserConfig(str(tmp_path), resource_retry_attempts=3, resource_retry_delay=0)
    )
    repository.start()
    try:
        detail = repository.get_detail(run_uuid)
    finally:
        repository.close()

    assert attempts == 3
    assert detail.summary.name == "Cold registry"


def test_snapshot_analysis_is_cached_and_missing_run_graph_does_not_reanalyze_snapshots(tmp_path: Path) -> None:
    run_uuid = uuid.uuid4()
    snapshot_ids = [uuid.uuid4(), uuid.uuid4()]
    pulse = np.concatenate((np.zeros(25), np.full(15, 3.0)))
    data = np.column_stack((np.arange(80, dtype=float) * 1e-9, np.tile(pulse, 2)))
    indexes = np.array([[0, 10.0], [40, 20.0]])
    library = Library(str(tmp_path))
    entry = library.create_entry("Cached analysis", "Fixture")
    entry.set_tag("experiment", "exposure")
    entry.set_tag("run", run_uuid.hex)
    for offset, snapshot_id in enumerate(snapshot_ids):
        with entry.resource(f"snap_{snapshot_id}.npz", "snapshot", "wb") as resource:
            np.savez(resource, data=data, indexes=indexes)
        with entry.resource(f"snap_{snapshot_id}.json", "snap_meta", "w") as resource:
            json.dump(
                {
                    "start": offset * 2_000_000_000,
                    "end": offset * 2_000_000_000 + 1_000_000_000,
                    "is_step_exposure": False,
                },
                resource,
            )
    library.close()

    analysis_calls = 0

    def counting_analyzer(waveform_path: Path, metadata_path: Path):
        nonlocal analysis_calls
        analysis_calls += 1
        return analyze_registered_snapshot(waveform_path, metadata_path)

    repository = ExperimentBrowserRepository(
        ExperimentBrowserConfig(str(tmp_path), resource_retry_delay=0),
        snapshot_analyzer=counting_analyzer,
    )
    repository.start()
    try:
        first = repository.get_snapshot_analysis(run_uuid, snapshot_ids[0])
        second = repository.get_snapshot_analysis(run_uuid, snapshot_ids[0])
        series = repository.get_run_dose_series(run_uuid)
    finally:
        repository.close()

    assert first == second
    assert analysis_calls == 1
    assert series.status == "missing"
    assert series.points == ()


def test_missing_run_graph_does_not_submit_snapshot_analysis_work(tmp_path: Path) -> None:
    run_uuid = uuid.uuid4()
    snapshot_ids = [uuid.uuid4() for _ in range(5)]
    pulse = np.concatenate((np.zeros(25), np.full(15, 3.0)))
    data = np.column_stack((np.arange(80, dtype=float) * 1e-9, np.tile(pulse, 2)))
    indexes = np.array([[0, 10.0], [40, 20.0]])
    library = Library(str(tmp_path))
    entry = library.create_entry("Parallel analysis", "Fixture")
    entry.set_tag("experiment", "exposure")
    entry.set_tag("run", run_uuid.hex)
    for index, snapshot_id in enumerate(snapshot_ids):
        start = (len(snapshot_ids) - index) * 2_000_000_000
        with entry.resource(f"snap_{snapshot_id}.npz", "snapshot", "wb") as resource:
            np.savez(resource, data=data, indexes=indexes)
        with entry.resource(f"snap_{snapshot_id}.json", "snap_meta", "w") as resource:
            json.dump({"start": start, "end": start + 1_000_000_000, "is_step_exposure": False}, resource)
    library.close()

    analysis_started = threading.Event()

    def blocking_analyzer(waveform_path: Path, metadata_path: Path):
        analysis_started.set()
        return analyze_registered_snapshot(waveform_path, metadata_path)

    repository = ExperimentBrowserRepository(
        ExperimentBrowserConfig(
            str(tmp_path),
            resource_retry_delay=0,
        ),
        snapshot_analyzer=blocking_analyzer,
    )
    repository.start()
    try:
        series = repository.get_run_dose_series(run_uuid)
    finally:
        repository.close()

    assert analysis_started.is_set() is False
    assert series.status == "missing"


def test_ensure_run_dose_series_returns_graph_validation_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_uuid = uuid.uuid4()
    library = Library(str(tmp_path))
    entry = library.create_entry("Graph validation", "Fixture")
    entry.set_tag("experiment", "exposure")
    entry.set_tag("run", run_uuid.hex)
    library.close()

    def reject_graph(*_args, **_kwargs):
        raise repository_module.ExposureGraphError("Legacy graph data cannot be reconciled.")

    monkeypatch.setattr(repository_module, "ensure_exposure_graph", reject_graph)
    repository = ExperimentBrowserRepository(ExperimentBrowserConfig(str(tmp_path)))
    repository.start()
    try:
        series = repository.ensure_run_dose_series(run_uuid)
        detail = repository.get_detail(run_uuid)
    finally:
        repository.close()

    assert series.status == "error"
    assert series.errors == ("Legacy graph data cannot be reconciled.",)
    assert detail.summary.run_id == run_uuid