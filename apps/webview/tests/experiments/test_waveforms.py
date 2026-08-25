from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from ipi_webview.experiments.waveforms import (
    SnapshotMetadataError,
    analyze_hdf5_snapshot,
    analyze_registered_snapshot,
    load_hdf5_voltage_points,
    load_voltage_points,
)


def _write_snapshot(tmp_path: Path, metadata: dict) -> tuple[Path, Path]:
    points_per_pulse = 40
    pulse = np.concatenate((np.zeros(25), np.full(points_per_pulse - 25, 3.0)))
    data = np.column_stack((np.arange(80, dtype=float) * 1e-9, np.tile(pulse, 2)))
    indexes = np.array([[0, 10.0], [40, 20.0]])
    waveform_path = tmp_path / "snap.npz"
    metadata_path = tmp_path / "snap.json"
    np.savez(waveform_path, data=data, indexes=indexes)
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    return waveform_path, metadata_path


def test_snapshot_analysis_backfills_missing_dose_and_step_mode_atomically(tmp_path: Path) -> None:
    waveform_path, metadata_path = _write_snapshot(
        tmp_path,
        {"start": 0, "end": 1_000_000_000, "unknown_key": {"kept": True}},
    )

    first = analyze_registered_snapshot(waveform_path, metadata_path)
    saved = json.loads(metadata_path.read_text(encoding="utf-8"))
    second = analyze_registered_snapshot(waveform_path, metadata_path)

    assert first.metadata_backfilled is True
    assert first.step_mode_source == "inferred"
    assert saved["unknown_key"] == {"kept": True}
    assert saved["dose"] == pytest.approx(first.total_dose_mj_cm2)
    assert saved["is_step_exposure"] is False
    assert second.metadata_backfilled is False
    assert second.total_dose_mj_cm2 == pytest.approx(first.total_dose_mj_cm2)


def test_snapshot_analysis_trusts_provided_step_mode_and_validates_metadata(tmp_path: Path) -> None:
    waveform_path, metadata_path = _write_snapshot(
        tmp_path,
        {"start": 0, "end": 1_000_000_000, "is_step_exposure": True},
    )

    result = analyze_registered_snapshot(waveform_path, metadata_path)

    assert result.step_mode_source == "provided"
    assert result.analysis.is_step_exposure is True
    assert result.analysis.effective_duration_seconds == pytest.approx(10.0)

    waveform_path, metadata_path = _write_snapshot(tmp_path, {"start": 0, "end": 1, "dose": "nan"})
    with pytest.raises(SnapshotMetadataError, match="dose"):
        analyze_registered_snapshot(waveform_path, metadata_path)


def test_snapshot_analysis_uses_persisted_exposure_start_for_runtime(tmp_path: Path) -> None:
    waveform_path, metadata_path = _write_snapshot(
        tmp_path,
        {"start": 0, "end": 1_000_000_000, "is_step_exposure": False, "exposure_start_ns": 400_000_000},
    )

    result = analyze_registered_snapshot(waveform_path, metadata_path)

    assert result.analysis.effective_duration_seconds == pytest.approx(1.0)
    assert result.analysis.runtime_contribution_seconds == pytest.approx(0.6)


def test_snapshot_analysis_survives_metadata_backfill_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    waveform_path, metadata_path = _write_snapshot(tmp_path, {"start": 0, "end": 1_000_000_000})

    def fail_replace(_source, _destination):
        raise OSError("cloud provider rejected write")

    monkeypatch.setattr(os, "replace", fail_replace)
    result = analyze_registered_snapshot(waveform_path, metadata_path)

    assert result.total_dose_mj_cm2 > 0
    assert result.metadata_backfilled is False
    assert result.backfill_error is not None
    assert "backfill" in result.backfill_error


def test_voltage_points_reconstruct_elapsed_time_when_each_pulse_resets_to_zero(tmp_path: Path) -> None:
    local_time = np.linspace(0.0, 10e-6, 1000)
    data = np.column_stack((np.tile(local_time, 3), np.arange(3000, dtype=float)))
    indexes = np.array([[0, 100.0], [1000, 100.01], [2000, 100.02]])
    waveform_path = tmp_path / "reset-time.npz"
    np.savez(waveform_path, data=data, indexes=indexes)

    elapsed, volts = load_voltage_points(waveform_path)

    assert len(elapsed) == 3000
    assert np.all(np.diff(elapsed) >= 0)
    assert elapsed[0] == 0.0
    assert elapsed[1000] == pytest.approx(0.01)
    assert elapsed[2000] == pytest.approx(0.02)
    assert elapsed[-1] == pytest.approx(0.02001)
    assert np.array_equal(volts, data[:, 1])


def test_hdf5_snapshot_analysis_uses_native_integrals_and_calibration_provenance(tmp_path: Path) -> None:
    from chamber_ctl.data.calibration import CalibrationProfile
    from euv_acquisition.analysis import analyze_pulse
    from euv_acquisition.models import CaptureConfig, CapturedPulse, PulseRecord, SnapshotCloseReason
    from euv_acquisition.snapshot import SnapshotStore

    config = CaptureConfig(sample_rate_hz=1_000_000.0, window_seconds=4e-6, pretrigger_seconds=1e-6)
    profile = CalibrationProfile(
        profile_id=__import__("uuid").uuid4(),
        revision=1,
        name="Fixture profile",
        created_at=1.0,
        algorithm_version="dose-v1",
        signal_polarity=1,
        load_resistance_ohms=50.0,
        photodiode_responsivity_a_per_w=0.14,
        illuminated_area_cm2=0.05,
    )
    store = SnapshotStore(tmp_path / "source")
    session_id = __import__("uuid").uuid4()
    samples = (
        np.asarray([0.0, 0.2, 0.2, 0.0], dtype=np.float32),
        np.asarray([0.0, -0.3, -0.3, 0.0], dtype=np.float32),
    )
    manifest = store.write(
        [
            PulseRecord(session_id, index, CapturedPulse(pulse, 1_000_000_000 + index * 10_000_000, index), analyze_pulse(pulse, config))
            for index, pulse in enumerate(samples)
        ],
        config,
        SnapshotCloseReason.CAPTURE_STOP,
        source_kind="simulated",
        source_id="test",
    )
    calibration_path = tmp_path / "euv_calibration_profile.json"
    calibration_path.write_text(json.dumps(profile.to_dict()), encoding="utf-8")

    result = analyze_hdf5_snapshot(store.path_for(manifest), calibration_path)
    elapsed, volts = load_hdf5_voltage_points(store.path_for(manifest))

    assert result.step_mode_source == "native"
    assert result.metadata_backfilled is False
    assert result.total_dose_mj_cm2 > 0
    assert len(result.analysis.pulse_doses_mj_cm2) == 2
    assert result.analysis.pulse_doses_mj_cm2[1] == 0.0
    assert elapsed[0] == 0.0
    assert elapsed[4] == pytest.approx(0.01)
    assert volts.tolist() == pytest.approx([*samples[0], *samples[1]])