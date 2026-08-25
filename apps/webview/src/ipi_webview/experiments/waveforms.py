from __future__ import annotations

import json
import math
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from chamber_ctl.data.calibration import CalibrationProfile
from chamber_ctl.subsystems.oscilloscope import SnapshotAnalysis, analyze_snapshot
from euv_acquisition.snapshot import read_snapshot


class SnapshotMetadataError(ValueError):
    """A registered snapshot or its metadata cannot be analyzed."""


class SnapshotMetadataConflict(RuntimeError):
    """Snapshot metadata changed while a backfill was being prepared."""


class SnapshotResourceUnavailable(RuntimeError):
    """A registered snapshot resource could not currently be hydrated."""


@dataclass(frozen=True, slots=True)
class AnalyzedSnapshot:
    analysis: SnapshotAnalysis
    total_dose_mj_cm2: float
    metadata: dict[str, Any]
    metadata_backfilled: bool
    step_mode_source: str
    backfill_error: str | None


_file_locks: dict[Path, threading.Lock] = {}
_file_locks_guard = threading.Lock()


def _file_lock(path: Path) -> threading.Lock:
    resolved_path = path.resolve()
    with _file_locks_guard:
        lock = _file_locks.get(resolved_path)
        if lock is None:
            lock = threading.Lock()
            _file_locks[resolved_path] = lock
        return lock


def _source_signature(path: Path) -> tuple[int, int]:
    stat_result = path.stat()
    return stat_result.st_mtime_ns, stat_result.st_size


def _finite_number(value: Any, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise SnapshotMetadataError(f"Snapshot metadata field {field_name!r} must be numeric.") from exc
    if not math.isfinite(parsed):
        raise SnapshotMetadataError(f"Snapshot metadata field {field_name!r} must be finite.")
    return parsed


def _load_metadata(path: Path) -> tuple[dict[str, Any], tuple[int, int]]:
    try:
        signature = _source_signature(path)
        with path.open("r", encoding="utf-8") as source:
            metadata = json.load(source)
    except OSError as exc:
        raise SnapshotResourceUnavailable("Snapshot metadata JSON is currently unavailable.") from exc
    except json.JSONDecodeError as exc:
        raise SnapshotMetadataError("Snapshot metadata JSON is malformed.") from exc
    if not isinstance(metadata, dict):
        raise SnapshotMetadataError("Snapshot metadata JSON must contain an object.")
    return metadata, signature


def _write_metadata_atomically(path: Path, metadata: dict[str, Any], expected_signature: tuple[int, int]) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temp_path = Path(temporary.name)
            json.dump(metadata, temporary, sort_keys=True)
            temporary.flush()
            os.fsync(temporary.fileno())
        if _source_signature(path) != expected_signature:
            raise SnapshotMetadataConflict("Snapshot metadata changed before atomic backfill.")
        os.replace(temp_path, path)
        temp_path = None
    except OSError as exc:
        raise SnapshotMetadataError("Snapshot metadata backfill could not be written.") from exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def analyze_registered_snapshot(waveform_path: Path, metadata_path: Path) -> AnalyzedSnapshot:
    """Analyze one registry-validated snapshot and atomically backfill only missing metadata fields."""

    waveform_path = Path(waveform_path)
    metadata_path = Path(metadata_path)
    lock = _file_lock(metadata_path)
    with lock:
        metadata, metadata_signature = _load_metadata(metadata_path)
        try:
            with np.load(waveform_path, allow_pickle=False) as snapshot:
                data = snapshot["data"]
                indexes = snapshot["indexes"]
        except OSError as exc:
            raise SnapshotResourceUnavailable("Snapshot waveform is currently unavailable.") from exc
        except (KeyError, ValueError) as exc:
            raise SnapshotMetadataError("Snapshot waveform is malformed.") from exc

        start = _finite_number(metadata.get("start"), "start")
        end = _finite_number(metadata.get("end"), "end")
        raw_step_mode = metadata.get("is_step_exposure")
        if raw_step_mode is not None and not isinstance(raw_step_mode, bool):
            raise SnapshotMetadataError("Snapshot metadata is_step_exposure must be boolean.")
        if "exposure_start_ns" in metadata:
            raw_exposure_start = metadata["exposure_start_ns"]
            exposure_start_ns = None if raw_exposure_start is None else _finite_number(
                raw_exposure_start,
                "exposure_start_ns",
            )
            analysis = analyze_snapshot(
                start,
                end,
                data,
                indexes,
                is_step_exposure=raw_step_mode,
                exposure_start_ns=exposure_start_ns,
            )
        else:
            analysis = analyze_snapshot(start, end, data, indexes, is_step_exposure=raw_step_mode)
        step_mode_source = "provided" if raw_step_mode is not None else "inferred"

        metadata_backfilled = False
        backfill_required = False
        backfill_error = None
        updated_metadata = dict(metadata)
        if "dose" in metadata:
            total_dose = _finite_number(metadata["dose"], "dose")
        else:
            total_dose = analysis.total_dose_mj_cm2
            updated_metadata["dose"] = total_dose
            backfill_required = True
        if raw_step_mode is None:
            updated_metadata["is_step_exposure"] = analysis.is_step_exposure
            backfill_required = True
        if backfill_required:
            try:
                _write_metadata_atomically(metadata_path, updated_metadata, metadata_signature)
            except (SnapshotMetadataError, SnapshotMetadataConflict) as exc:
                backfill_error = str(exc)
            else:
                metadata = updated_metadata
                metadata_backfilled = True

        return AnalyzedSnapshot(
            analysis=analysis,
            total_dose_mj_cm2=total_dose,
            metadata=metadata,
            metadata_backfilled=metadata_backfilled,
            step_mode_source=step_mode_source,
            backfill_error=backfill_error,
        )


def analyze_hdf5_snapshot(waveform_path: Path, calibration_path: Path) -> AnalyzedSnapshot:
    """Analyze a native HDF5 capture with its immutable run calibration provenance."""

    try:
        contents = read_snapshot(waveform_path)
        with Path(calibration_path).open("r", encoding="utf-8") as source:
            calibration = CalibrationProfile.from_dict(json.load(source))
    except OSError as exc:
        raise SnapshotResourceUnavailable("Native HDF5 snapshot resources are currently unavailable.") from exc
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SnapshotMetadataError("Native HDF5 snapshot or calibration provenance is malformed.") from exc

    captured_at_seconds = np.asarray(contents.captured_at_unix_ns, dtype=np.float64) / 1e9
    if len(captured_at_seconds) == 0 or np.any(np.diff(captured_at_seconds) < 0):
        raise SnapshotMetadataError("Native HDF5 capture timestamps must be ordered and non-empty.")
    pulse_doses = np.asarray(
        [max(0.0, calibration.dose_for_integral(float(integral))) for integral in contents.integral_volt_seconds],
        dtype=float,
    )
    if not np.isfinite(pulse_doses).all():
        raise SnapshotMetadataError("Native HDF5 calibration produced non-finite pulse doses.")
    total_dose = float(np.sum(pulse_doses))
    pulse_span = float(captured_at_seconds[-1] - captured_at_seconds[0])
    average_pulse_dose = float(np.mean(pulse_doses))
    delivered_rate = total_dose / pulse_span if pulse_span > 0 else 0.0
    analysis = SnapshotAnalysis(
        average_pulse_dose_mj_cm2=average_pulse_dose,
        pulse_times_seconds=captured_at_seconds,
        pulse_indexes=np.arange(len(pulse_doses), dtype=int),
        pulse_doses_mj_cm2=pulse_doses,
        pulse_peaks_volts=np.asarray(contents.maximum_volts, dtype=float),
        pulse_span_seconds=pulse_span,
        wall_duration_seconds=pulse_span,
        is_step_exposure=False,
        inferred_step_exposure=False,
        effective_duration_seconds=pulse_span,
        runtime_contribution_seconds=pulse_span,
        total_dose_mj_cm2=total_dose,
        delivered_dose_rate_mj_cm2_s=delivered_rate,
    )
    return AnalyzedSnapshot(
        analysis=analysis,
        total_dose_mj_cm2=total_dose,
        metadata={
            "start": int(contents.captured_at_unix_ns[0]),
            "end": int(contents.captured_at_unix_ns[-1]),
            "snapshot_format": "euv_hdf5",
        },
        metadata_backfilled=False,
        step_mode_source="native",
        backfill_error=None,
    )


def load_voltage_points(waveform_path: Path, *, time_mode: str = "wall") -> tuple[np.ndarray, np.ndarray]:
    if time_mode not in {"wall", "apparent"}:
        raise ValueError("Snapshot time mode must be wall or apparent.")
    try:
        with np.load(Path(waveform_path), allow_pickle=False) as snapshot:
            data = np.asarray(snapshot["data"], dtype=float)
            indexes = np.asarray(snapshot["indexes"], dtype=float)
    except OSError as exc:
        raise SnapshotResourceUnavailable("Snapshot waveform is currently unavailable.") from exc
    except (KeyError, ValueError) as exc:
        raise SnapshotMetadataError("Snapshot waveform is malformed.") from exc
    if data.ndim != 2 or data.shape[1] < 2:
        raise SnapshotMetadataError("Snapshot waveform must contain time and voltage columns.")
    points = data[:, :2]
    if not np.isfinite(points).all():
        raise SnapshotMetadataError("Snapshot waveform contains non-finite points.")
    if len(points) == 0:
        return np.array([], dtype=float), np.array([], dtype=float)
    local_times = points[:, 0]
    if indexes.ndim != 2 or indexes.shape[1] < 2 or len(indexes) == 0:
        elapsed = local_times - local_times[0]
        if np.any(np.diff(elapsed) < 0):
            raise SnapshotMetadataError("Snapshot waveform time resets without pulse indexes.")
        return elapsed, points[:, 1].copy()

    sample_positions = indexes[:, 0]
    pulse_times = indexes[:, 1]
    if not np.isfinite(indexes[:, :2]).all() or not np.equal(sample_positions, np.floor(sample_positions)).all():
        raise SnapshotMetadataError("Snapshot pulse indexes must be finite integer positions and finite times.")
    sample_positions = sample_positions.astype(int)
    if (
        sample_positions[0] != 0
        or np.any(sample_positions < 0)
        or np.any(sample_positions >= len(points))
        or np.any(np.diff(sample_positions) <= 0)
        or np.any(np.diff(pulse_times) < 0)
    ):
        raise SnapshotMetadataError("Snapshot pulse indexes are not ordered across the waveform.")

    elapsed = np.empty(len(points), dtype=float)
    first_pulse_time = pulse_times[0]
    apparent_offset = 0.0
    for pulse_index, start in enumerate(sample_positions):
        stop = sample_positions[pulse_index + 1] if pulse_index + 1 < len(sample_positions) else len(points)
        segment_times = local_times[start:stop]
        segment_elapsed = segment_times - segment_times[0]
        if np.any(np.diff(segment_elapsed) < 0):
            raise SnapshotMetadataError("Snapshot waveform time is not ordered within a pulse.")
        if time_mode == "wall":
            elapsed[start:stop] = pulse_times[pulse_index] - first_pulse_time + segment_elapsed
        else:
            elapsed[start:stop] = apparent_offset + segment_elapsed
            apparent_offset = float(elapsed[stop - 1])
    if np.any(np.diff(elapsed) < 0):
        raise SnapshotMetadataError("Reconstructed snapshot time is not monotonic.")
    return elapsed, points[:, 1].copy()


def load_hdf5_voltage_points(waveform_path: Path, *, time_mode: str = "wall") -> tuple[np.ndarray, np.ndarray]:
    if time_mode not in {"wall", "apparent"}:
        raise ValueError("Snapshot time mode must be wall or apparent.")
    try:
        contents = read_snapshot(waveform_path)
    except OSError as exc:
        raise SnapshotResourceUnavailable("Native HDF5 snapshot is currently unavailable.") from exc
    except (TypeError, ValueError) as exc:
        raise SnapshotMetadataError("Native HDF5 snapshot is malformed.") from exc

    sample_count = contents.samples_v.shape[1]
    local_elapsed = np.arange(sample_count, dtype=float) / contents.capture_config.sample_rate_hz
    captured_at_seconds = np.asarray(contents.captured_at_unix_ns, dtype=np.float64) / 1e9
    if len(captured_at_seconds) == 0 or np.any(np.diff(captured_at_seconds) < 0):
        raise SnapshotMetadataError("Native HDF5 capture timestamps must be ordered and non-empty.")
    elapsed = np.empty(len(captured_at_seconds) * sample_count, dtype=float)
    first_capture = captured_at_seconds[0]
    apparent_offset = 0.0
    for index, capture_time in enumerate(captured_at_seconds):
        start = index * sample_count
        stop = start + sample_count
        if time_mode == "wall":
            elapsed[start:stop] = capture_time - first_capture + local_elapsed
        else:
            elapsed[start:stop] = apparent_offset + local_elapsed
            apparent_offset = float(elapsed[stop - 1])
    if np.any(np.diff(elapsed) < 0):
        raise SnapshotMetadataError("Native HDF5 waveform time is not monotonic.")
    return elapsed, np.asarray(contents.samples_v, dtype=float).reshape(-1)