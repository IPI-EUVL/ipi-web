from __future__ import annotations

import math
import os
import queue
import json
import re
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, BinaryIO, Protocol
from uuid import UUID

from ipi_ecs.db.db_library import Library
from ipi_ecs.subsystems.experiment_controller import ExperimentReader
from ipi_ecs.subsystems.run_events import RunEvent, RunEventTimeline, load_run_event_timeline
from chamber_ctl.data.dose_analysis import hdf5_snapshot_session_id, resolve_authoritative_hdf5_session
from chamber_ctl.data.exposure_graph import ExposureGraph, ExposureGraphError, ExposureGraphValidationError, ensure_exposure_graph, read_exposure_graph
from chamber_ctl.data.observer_analysis import load_observer_dose_products

from ipi_webview.experiments.export import ExperimentExportArchive, build_experiment_zip
from ipi_webview.experiments.models import (
    ExperimentBrowserConfig,
    ExperimentDataIssue,
    ExperimentDetail,
    ExposureEvent,
    ExposureEventTimeline,
    ExperimentFilterOptions,
    ExperimentFilters,
    ExperimentListItem,
    ExperimentMetrics,
    ExperimentPage,
    GraphAnnotation,
    LogRangeSummary,
    MetricMeasurement,
    ObserverDoseComparison,
    ObserverDoseCompleteness,
    ObserverDosePoint,
    ObserverDoseSeries,
    RegisteredResource,
    RunDosePoint,
    RunDoseSeries,
    SnapshotSummary,
    SnapshotAnalysisSummary,
    SnapshotGraphSeries,
)
from ipi_webview.experiments.waveforms import (
    AnalyzedSnapshot,
    SnapshotMetadataConflict,
    SnapshotMetadataError,
    SnapshotResourceUnavailable,
    analyze_hdf5_snapshot,
    analyze_registered_snapshot,
    load_hdf5_voltage_points,
    load_voltage_points,
)


class ExperimentRepositoryUnavailable(RuntimeError):
    """The indexed experiment store could not be read at this time."""


class ExperimentIntegrityError(ValueError):
    """An indexed experiment record cannot be represented safely."""


class ExperimentNotFoundError(LookupError):
    """The requested run is not indexed for this experiment type."""


class ExperimentResourceUnavailable(RuntimeError):
    """A registered resource could not be hydrated after bounded retries."""


class ExperimentResponseTooLarge(RuntimeError):
    """A requested experiment response exceeds its configured point budget."""


class ExperimentReaderLike(Protocol):
    def query(
        self,
        query: dict,
        limit: int | None = None,
        *,
        offset: int = 0,
        cursor: object | None = None,
    ) -> list[Any]: ...

    def count(self, query: dict | None = None) -> int: ...

    def close(self) -> None: ...


ExperimentReaderFactory = Callable[..., ExperimentReaderLike]
SnapshotAnalyzer = Callable[[Path, Path], AnalyzedSnapshot]


@dataclass(slots=True)
class _Command:
    operation: Callable[[ExperimentReaderLike], Any]
    response: queue.Queue[tuple[bool, Any]]


@dataclass(slots=True)
class OpenResource:
    resource: RegisteredResource
    file: BinaryIO

    def close(self) -> None:
        self.file.close()


@dataclass(frozen=True, slots=True)
class _SnapshotPaths:
    waveform: Path
    metadata: Path | None
    snapshot_format: str
    calibration: Path | None


@dataclass(frozen=True, slots=True)
class _CaptureTimelinePoint:
    final_sequence: int
    cumulative_dose_mj_cm2: float
    cumulative_runtime_seconds: float


@dataclass(frozen=True, slots=True)
class _CachedAnalysis:
    signature: tuple[tuple[int, int], ...]
    result: AnalyzedSnapshot


@dataclass(frozen=True, slots=True)
class _RunEventData:
    timeline: RunEventTimeline
    wall_time_origin_unix_ns: int | None


def _run_event_data(record: Any) -> _RunEventData:
    timeline = load_run_event_timeline(record.get_record())
    origin = next(
        (
            event.producer_unix_ns
            for event in timeline.events
            if event.kind == "lifecycle.phase" and event.payload.get("phase") == "PREINIT"
        ),
        None,
    )
    return _RunEventData(timeline, origin)


def _exposure_event(event: RunEvent) -> ExposureEvent:
    return ExposureEvent(
        event_id=event.event_id,
        stream_id=event.stream_id,
        stream_name=event.stream_name,
        sequence=event.sequence,
        kind=event.kind,
        producer_unix_ns=event.producer_unix_ns,
        producer_monotonic_ns=event.producer_monotonic_ns,
        ingest_unix_ns=event.ingest_unix_ns,
        payload=dict(event.payload),
        capture_session_id=event.capture_session_id,
        next_sequence=event.next_sequence,
        runtime_seconds=event.runtime_seconds,
    )


def _timeline_issue_text(timeline: RunEventTimeline) -> tuple[str, ...]:
    return tuple(issue.message for issue in timeline.issues)


def _annotation_category(event: RunEvent) -> str | None:
    if event.kind == "lifecycle.phase":
        return "lifecycle"
    if event.kind == "timing.triggers_enabled":
        return "triggers"
    if event.kind == "timing.euv_transmitting":
        return "transmitting"
    return None


def _annotation_label(event: RunEvent) -> str:
    if event.kind == "lifecycle.phase":
        outcome = event.payload.get("outcome")
        phase = str(event.payload.get("phase", "Unknown"))
        return f"{phase} ({outcome})" if outcome else phase
    value = bool(event.payload.get("value"))
    if event.kind == "timing.triggers_enabled":
        return "Triggers enabled" if value else "Triggers disabled"
    if event.kind == "timing.euv_transmitting":
        return "EUV transmitting" if value else "EUV blocked"
    return event.kind


def _run_annotations(
    event_data: _RunEventData,
    *,
    time_mode: str,
    final_runtime_seconds: float,
    final_wall_unix_ns: int | None,
) -> tuple[GraphAnnotation, ...]:
    if time_mode not in {"runtime", "wall"}:
        raise ValueError("Run annotation time mode must be runtime or wall.")
    origin = event_data.wall_time_origin_unix_ns
    if time_mode == "wall" and origin is None:
        return ()

    def coordinate(event: RunEvent) -> float | None:
        if time_mode == "wall":
            assert origin is not None
            return (event.producer_unix_ns - origin) / 1e9
        if event.kind == "lifecycle.phase":
            return final_runtime_seconds if event.payload.get("phase") in {"STOPPING", "STOPPED"} else 0.0
        return event.runtime_seconds

    end_coordinate = (
        final_runtime_seconds
        if time_mode == "runtime"
        else None if final_wall_unix_ns is None or origin is None else (final_wall_unix_ns - origin) / 1e9
    )
    annotations: list[GraphAnnotation] = []
    state_events: dict[str, list[tuple[RunEvent, float]]] = {"triggers": [], "transmitting": []}
    for event in event_data.timeline.events:
        category = _annotation_category(event)
        if category is None:
            continue
        x = coordinate(event)
        if x is None:
            continue
        if category == "lifecycle":
            annotations.append(
                GraphAnnotation(event.event_id, category, "point", _annotation_label(event), x, None, None,
                                event.stream_name, event.producer_unix_ns, "producer")
            )
        else:
            state_events[category].append((event, x))
    for category, items in state_events.items():
        for index, (event, x) in enumerate(items):
            next_x = items[index + 1][1] if index + 1 < len(items) else end_coordinate
            if next_x is not None and next_x < x:
                continue
            annotations.append(
                GraphAnnotation(event.event_id, category, "interval", _annotation_label(event), x, next_x,
                                bool(event.payload.get("value")), event.stream_name, event.producer_unix_ns,
                                "runtime_hint" if time_mode == "runtime" else "producer")
            )
    return tuple(sorted(annotations, key=lambda item: (item.x, str(item.event_id))))


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _tag_text(tags: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = _optional_text(tags.get(name))
        if value is not None:
            return value
    return None


def _tag_float(tags: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = _optional_float(tags.get(name))
        if value is not None:
            return value
    return None


def _run_id(tags: dict[str, Any]) -> UUID:
    try:
        return UUID(str(tags.get("run")))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ExperimentIntegrityError("Exposure record has an invalid or missing run UUID tag.") from exc


def _list_item_from_record(record: Any) -> ExperimentListItem:
    entry = record.get_record()
    if entry is None:
        raise ExperimentIntegrityError("Exposure record has no indexed entry.")

    tags = entry.get_tags() or {}
    actual_dose = _tag_float(tags, "dose")
    runtime = _tag_float(tags, "runtime")
    rate = actual_dose / runtime if actual_dose is not None and runtime is not None and runtime > 0 else None
    exposed_thickness = _tag_float(tags, "avg_exposed_area_thickness_nm")
    blank_thickness = _tag_float(tags, "avg_blank_area_thickness_nm")
    percent_development = (
        (1.0 - (exposed_thickness / blank_thickness)) * 100.0
        if exposed_thickness is not None and blank_thickness not in (None, 0.0)
        else None
    )
    return ExperimentListItem(
        run_id=_run_id(tags),
        created_at=float(entry.get_timestamp()),
        name=str(entry.get_name() or ""),
        description=str(entry.get_description() or ""),
        sample=_tag_text(tags, "sample", "sample_type", "sample_number"),
        operator=_tag_text(tags, "operator"),
        zr_filter=_tag_text(tags, "zr_filter"),
        target_dose=_tag_float(tags, "target_dose"),
        target_time=_tag_float(tags, "target_time"),
        actual_dose=actual_dose,
        runtime=runtime,
        effective_dose_rate=rate,
        exposed_thickness_nm=exposed_thickness,
        blank_thickness_nm=blank_thickness,
        percent_development=percent_development,
        status=_tag_text(tags, "status"),
        end_reason=_tag_text(tags, "abort_reason"),
    )


def _library_filters(filters: ExperimentFilters) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if filters.name is not None:
        query["name"] = filters.name
    if filters.created_min is not None:
        query["created_min"] = filters.created_min
    if filters.created_max is not None:
        query["created_max"] = filters.created_max

    tags: dict[str, Any] = {}
    if filters.min_actual_dose is not None or filters.max_actual_dose is not None:
        actual_dose: dict[str, float] = {}
        if filters.min_actual_dose is not None:
            actual_dose["min"] = filters.min_actual_dose
        if filters.max_actual_dose is not None:
            actual_dose["max"] = filters.max_actual_dose
        tags["dose"] = actual_dose
    if filters.min_target_dose is not None or filters.max_target_dose is not None:
        target_dose: dict[str, float] = {}
        if filters.min_target_dose is not None:
            target_dose["min"] = filters.min_target_dose
        if filters.max_target_dose is not None:
            target_dose["max"] = filters.max_target_dose
        tags["target_dose"] = target_dose
    if filters.min_runtime is not None or filters.max_runtime is not None:
        runtime: dict[str, float] = {}
        if filters.min_runtime is not None:
            runtime["min"] = filters.min_runtime
        if filters.max_runtime is not None:
            runtime["max"] = filters.max_runtime
        tags["runtime"] = runtime
    if filters.zr_filter is not None:
        tags["zr_filter"] = filters.zr_filter
    if filters.sample is not None:
        tags["sample"] = filters.sample
    if filters.operator is not None:
        tags["operator"] = filters.operator
    if tags:
        query["tags"] = tags
    return query


_SNAPSHOT_WAVEFORM = re.compile(r"^snap_([0-9a-fA-F-]{36})\.npz$")
_SNAPSHOT_METADATA = re.compile(r"^snap_([0-9a-fA-F-]{36})\.json$")
_SNAPSHOT_HDF5 = re.compile(r"^snap_([0-9a-fA-F-]{36})\.h5$")
_HDF5_SNAPSHOT_RESOURCE_TYPE = "euv_snapshot"
_CALIBRATION_PROVENANCE_RESOURCE = "euv_calibration_profile.json"
_CALIBRATION_PROVENANCE_RESOURCE_TYPE = "euv_calibration_profile"
_CAPTURE_TIMELINE_RESOURCE = "euv_capture_timeline.json"
_CAPTURE_TIMELINE_RESOURCE_TYPE = "euv_capture_timeline"


def _validate_resource_name(name: Any) -> str:
    if not isinstance(name, str) or not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ExperimentIntegrityError("Exposure registry contains an invalid resource name.")
    return name


def _registered_resource_declarations(
    entry: Any,
    config: ExperimentBrowserConfig,
) -> tuple[tuple[str, str], ...]:
    declarations = []
    try:
        registered_items = _retry_io(
            lambda: tuple(entry.list_resources()),
            attempts=config.resource_retry_attempts,
            delay=config.resource_retry_delay,
            retry_exceptions=(OSError, ValueError),
        )
    except ValueError as exc:
        raise ExperimentResourceUnavailable(
            f"Exposure registry remains unreadable after {config.resource_retry_attempts} attempts."
        ) from exc
    for raw_name, raw_type in registered_items:
        name = _validate_resource_name(raw_name)
        if not isinstance(raw_type, str) or not raw_type:
            raise ExperimentIntegrityError(f"Registered resource {name!r} has an invalid type.")
        declarations.append((name, raw_type))
    return tuple(sorted(declarations, key=lambda item: item[0].casefold()))


def _resource_path(data_path: str, entry: Any, name: str) -> Path:
    return _entry_folder_path(data_path, entry) / name


def _entry_folder_path(data_path: str, entry: Any) -> Path:
    foldername = entry.get_foldername()
    if not isinstance(foldername, str) or not foldername or Path(foldername).name != foldername:
        raise ExperimentIntegrityError("Exposure entry has an invalid folder name.")
    base_path = Path(data_path).resolve()
    folder_path = (base_path / foldername).resolve()
    if base_path != folder_path and base_path not in folder_path.parents:
        raise ExperimentIntegrityError("Exposure entry folder is outside the data root.")
    return folder_path


def _retry_io(
    operation: Callable[[], Any],
    *,
    attempts: int,
    delay: float,
    retry_exceptions: tuple[type[Exception], ...] = (OSError,),
) -> Any:
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except retry_exceptions:
            if attempt == attempts:
                raise
            if delay:
                time.sleep(delay)
    raise AssertionError("Resource retry loop exited unexpectedly.")


def _unavailable_message(name: str, attempts: int, exc: OSError) -> str:
    return f"Registered resource {name!r} is unavailable after {attempts} attempts ({type(exc).__name__})."


def _rolling_average(values: Any, window: int) -> tuple[float, ...]:
    normalized = tuple(float(value) for value in values)
    if window == 1 or not normalized:
        return normalized
    cumulative = [0.0]
    for value in normalized:
        cumulative.append(cumulative[-1] + value)
    return tuple(
        (cumulative[index + 1] - cumulative[max(0, index + 1 - window)])
        / (index + 1 - max(0, index + 1 - window))
        for index in range(len(normalized))
    )


def _registered_resources(entry: Any, config: ExperimentBrowserConfig) -> tuple[RegisteredResource, ...]:
    resources = []
    for name, resource_type in _registered_resource_declarations(entry, config):
        path = _resource_path(config.data_path, entry, name)
        try:
            stat_result = _retry_io(
                path.stat,
                attempts=config.resource_retry_attempts,
                delay=config.resource_retry_delay,
            )
        except OSError as exc:
            resources.append(
                RegisteredResource(
                    name=name,
                    resource_type=resource_type,
                    size_bytes=None,
                    available=False,
                    downloadable=False,
                    error=_unavailable_message(name, config.resource_retry_attempts, exc),
                )
            )
            continue
        resources.append(
            RegisteredResource(
                name=name,
                resource_type=resource_type,
                size_bytes=stat_result.st_size,
                available=True,
                downloadable=True,
                error=None,
            )
        )
    return tuple(resources)


def _snapshot_inventory(
    resources: tuple[RegisteredResource, ...],
) -> tuple[tuple[SnapshotSummary, ...], tuple[ExperimentDataIssue, ...]]:
    waveforms: dict[UUID, RegisteredResource] = {}
    metadata: dict[UUID, RegisteredResource] = {}
    hdf5_waveforms: dict[UUID, RegisteredResource] = {}
    issues = []
    for resource in resources:
        waveform_match = _SNAPSHOT_WAVEFORM.fullmatch(resource.name)
        metadata_match = _SNAPSHOT_METADATA.fullmatch(resource.name)
        hdf5_match = _SNAPSHOT_HDF5.fullmatch(resource.name)
        if waveform_match is not None:
            if resource.resource_type != "snapshot":
                issues.append(
                    ExperimentDataIssue(
                        "snapshots",
                        resource.name,
                        "integrity",
                        f"Snapshot waveform {resource.name!r} has an invalid registry type.",
                    )
                )
                continue
            waveforms[UUID(waveform_match.group(1))] = resource
        elif hdf5_match is not None:
            if resource.resource_type != _HDF5_SNAPSHOT_RESOURCE_TYPE:
                issues.append(
                    ExperimentDataIssue(
                        "snapshots",
                        resource.name,
                        "integrity",
                        f"Native HDF5 snapshot {resource.name!r} has an invalid registry type.",
                    )
                )
                continue
            hdf5_waveforms[UUID(hdf5_match.group(1))] = resource
        elif metadata_match is not None:
            if resource.resource_type != "snap_meta":
                issues.append(
                    ExperimentDataIssue(
                        "snapshots",
                        resource.name,
                        "integrity",
                        f"Snapshot metadata {resource.name!r} has an invalid registry type.",
                    )
                )
                continue
            metadata[UUID(metadata_match.group(1))] = resource
        elif resource.resource_type in {"snapshot", "snap_meta", _HDF5_SNAPSHOT_RESOURCE_TYPE}:
            issues.append(
                ExperimentDataIssue(
                    "snapshots",
                    resource.name,
                    "integrity",
                    f"Snapshot registry resource {resource.name!r} has an invalid filename.",
                )
            )

    snapshot_ids = waveforms.keys() | metadata.keys() | hdf5_waveforms.keys()
    snapshots = []
    for snapshot_id in sorted(snapshot_ids, key=str):
        waveform = waveforms.get(snapshot_id)
        snapshot_metadata = metadata.get(snapshot_id)
        hdf5_waveform = hdf5_waveforms.get(snapshot_id)
        if hdf5_waveform is not None and (waveform is not None or snapshot_metadata is not None):
            issues.append(
                ExperimentDataIssue(
                    "snapshots",
                    hdf5_waveform.name,
                    "integrity",
                    f"Snapshot {snapshot_id} mixes native HDF5 and legacy resources.",
                )
            )
            continue
        if hdf5_waveform is not None:
            snapshots.append(SnapshotSummary(snapshot_id, "euv_hdf5", hdf5_waveform, None))
            continue
        if waveform is None or snapshot_metadata is None:
            present_resource = snapshot_metadata or waveform
            missing_kind = "waveform" if waveform is None else "metadata"
            issues.append(
                ExperimentDataIssue(
                    "snapshots",
                    present_resource.name if present_resource is not None else None,
                    "integrity",
                    f"Snapshot {snapshot_id} is missing its registered {missing_kind} pair.",
                )
            )
            continue
        snapshots.append(SnapshotSummary(snapshot_id, "legacy_npz", waveform, snapshot_metadata))
    return tuple(snapshots), tuple(issues)


def _snapshot_summaries(resources: tuple[RegisteredResource, ...]) -> tuple[SnapshotSummary, ...]:
    snapshots, issues = _snapshot_inventory(resources)
    if issues:
        raise ExperimentIntegrityError(" ".join(issue.message for issue in issues))
    return snapshots


def _canonical_snapshot_inventory(
    entry: Any,
    resources: tuple[RegisteredResource, ...],
) -> tuple[tuple[SnapshotSummary, ...], tuple[ExperimentDataIssue, ...]]:
    snapshots, issues = _snapshot_inventory(resources)
    native = tuple(snapshot for snapshot in snapshots if snapshot.snapshot_format == "euv_hdf5")
    if not native:
        return snapshots, issues
    resource_types = {resource.name: resource.resource_type for resource in resources}
    try:
        authoritative_session = resolve_authoritative_hdf5_session(entry, resource_types)
    except OSError as exc:
        return (
            tuple(snapshot for snapshot in snapshots if snapshot.snapshot_format != "euv_hdf5"),
            issues + (
                ExperimentDataIssue(
                    "snapshots",
                    None,
                    "unavailable",
                    f"Authoritative capture provenance is unavailable: {exc}",
                ),
            ),
        )
    except ValueError as exc:
        return (
            tuple(snapshot for snapshot in snapshots if snapshot.snapshot_format != "euv_hdf5"),
            issues + (
                ExperimentDataIssue(
                    "snapshots",
                    "euv_capture_session.json",
                    "integrity",
                    f"Authoritative capture provenance is invalid: {exc}",
                ),
            ),
        )
    if authoritative_session is None:
        return snapshots, issues
    selected = []
    for snapshot in snapshots:
        if snapshot.snapshot_format != "euv_hdf5" or not snapshot.waveform.available:
            selected.append(snapshot)
            continue
        try:
            with entry.resource(snapshot.waveform.name, _HDF5_SNAPSHOT_RESOURCE_TYPE, "rb") as resource:
                session_id = hdf5_snapshot_session_id(
                    resource.read(),
                    filename=snapshot.waveform.name,
                )
        except (OSError, ValueError) as exc:
            return (
                tuple(item for item in snapshots if item.snapshot_format != "euv_hdf5"),
                issues + (
                    ExperimentDataIssue(
                        "snapshots",
                        snapshot.waveform.name,
                        "integrity",
                        f"Native snapshot source identity is invalid: {exc}",
                    ),
                ),
            )
        if session_id == authoritative_session:
            selected.append(snapshot)
    return tuple(selected), issues


def _capture_timeline_points(
    entry: Any,
    resources: tuple[RegisteredResource, ...],
    config: ExperimentBrowserConfig,
) -> dict[UUID, _CaptureTimelinePoint]:
    declared = [resource for resource in resources if resource.name == _CAPTURE_TIMELINE_RESOURCE]
    if not declared:
        return {}
    timeline_resource = declared[0]
    if timeline_resource.resource_type != _CAPTURE_TIMELINE_RESOURCE_TYPE:
        raise ExperimentIntegrityError("EUV capture timeline has an invalid registry type.")
    if not timeline_resource.available:
        raise ExperimentResourceUnavailable(timeline_resource.error or "EUV capture timeline is unavailable.")
    try:
        def read_timeline() -> Any:
            with _resource_path(config.data_path, entry, timeline_resource.name).open("r", encoding="utf-8") as source:
                return json.load(source)

        value = _retry_io(
            read_timeline,
            attempts=config.resource_retry_attempts,
            delay=config.resource_retry_delay,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentIntegrityError("EUV capture timeline is invalid or unavailable.") from exc
    if not isinstance(value, dict) or set(value) != {"schema_version", "snapshots"}:
        raise ExperimentIntegrityError("EUV capture timeline contains unknown or missing fields.")
    if value["schema_version"] != 1 or not isinstance(value["snapshots"], list):
        raise ExperimentIntegrityError("EUV capture timeline schema is invalid.")

    points = {}
    previous_sequence = -1
    previous_dose = 0.0
    previous_runtime = 0.0
    for item in value["snapshots"]:
        expected = {
            "snapshot_id",
            "final_sequence",
            "cumulative_dose_mj_cm2",
            "cumulative_runtime_seconds",
        }
        if not isinstance(item, dict) or set(item) != expected:
            raise ExperimentIntegrityError("EUV capture timeline point contains unknown or missing fields.")
        try:
            snapshot_id = UUID(str(item["snapshot_id"]))
            final_sequence = int(item["final_sequence"])
            cumulative_dose_mj_cm2 = float(item["cumulative_dose_mj_cm2"])
            cumulative_runtime_seconds = float(item["cumulative_runtime_seconds"])
        except (TypeError, ValueError) as exc:
            raise ExperimentIntegrityError("EUV capture timeline point is invalid.") from exc
        if (
            final_sequence < 0
            or final_sequence <= previous_sequence
            or not math.isfinite(cumulative_dose_mj_cm2)
            or cumulative_dose_mj_cm2 < previous_dose
            or not math.isfinite(cumulative_runtime_seconds)
            or cumulative_runtime_seconds < previous_runtime
            or snapshot_id in points
        ):
            raise ExperimentIntegrityError("EUV capture timeline points must be ordered and cumulative.")
        points[snapshot_id] = _CaptureTimelinePoint(
            final_sequence,
            cumulative_dose_mj_cm2,
            cumulative_runtime_seconds,
        )
        previous_sequence = final_sequence
        previous_dose = cumulative_dose_mj_cm2
        previous_runtime = cumulative_runtime_seconds
    return points


def _read_registered_json(
    entry: Any,
    resource_types: dict[str, str],
    name: str,
    config: ExperimentBrowserConfig,
) -> dict[str, Any] | None:
    resource_type = resource_types.get(name)
    if resource_type is None:
        return None
    try:
        def read_json() -> Any:
            with _resource_path(config.data_path, entry, name).open("r", encoding="utf-8") as resource:
                return json.load(resource)

        value = _retry_io(
            read_json,
            attempts=config.resource_retry_attempts,
            delay=config.resource_retry_delay,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentIntegrityError(f"Registered JSON resource {name!r} is invalid or unavailable.") from exc
    if not isinstance(value, dict):
        raise ExperimentIntegrityError(f"Registered JSON resource {name!r} must contain an object.")
    return value


def _settings_from_run_state(run_state: dict[str, Any] | None) -> dict[str, Any]:
    if not run_state:
        return {}
    config = run_state.get("config", {})
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except json.JSONDecodeError as exc:
            raise ExperimentIntegrityError("Registered run state has invalid settings JSON.") from exc
    if not isinstance(config, dict):
        raise ExperimentIntegrityError("Registered run state config must be an object.")
    return config


def _metric_average(measurements: tuple[MetricMeasurement, ...], spot_type: str) -> float | None:
    values = [measurement.thickness_nm for measurement in measurements if measurement.spot_type == spot_type]
    return sum(values) / len(values) if values else None


def _normalized_metrics(data: Any) -> tuple[MetricMeasurement, ...]:
    if not isinstance(data, dict):
        raise ValueError("Metric data must be a JSON object.")
    raw_measurements = data.get("measurements")
    if isinstance(raw_measurements, list):
        measurements = []
        for raw_measurement in raw_measurements:
            if not isinstance(raw_measurement, dict):
                continue
            spot_type = (_optional_text(raw_measurement.get("spot_type")) or "").lower()
            thickness = _optional_float(raw_measurement.get("thickness_nm"))
            goodness_of_fit = _optional_float(raw_measurement.get("goodness_of_fit"))
            if spot_type not in {"exposed", "blank"} or thickness is None or goodness_of_fit is None:
                continue
            measurements.append(
                MetricMeasurement(
                    spot_type=spot_type,
                    thickness_nm=thickness,
                    goodness_of_fit=goodness_of_fit,
                )
            )
        return tuple(measurements)

    raw_exposed = data.get("exposed_area_thickness_nm", [])
    raw_blank = data.get("blank_area_thickness_nm", [])
    raw_gof = data.get("goodness_of_fit", [])
    if not all(isinstance(values, list) for values in (raw_exposed, raw_blank, raw_gof)):
        raise ValueError("Legacy metric arrays must be lists.")
    exposed = [value for raw_value in raw_exposed if (value := _optional_float(raw_value)) is not None]
    blank = [value for raw_value in raw_blank if (value := _optional_float(raw_value)) is not None]
    measurements = []
    if len(raw_gof) == len(exposed) + len(blank):
        for index, thickness in enumerate(exposed):
            goodness_of_fit = _optional_float(raw_gof[index]) or 0.0
            measurements.append(MetricMeasurement("exposed", thickness, goodness_of_fit))
        for index, thickness in enumerate(blank):
            goodness_of_fit = _optional_float(raw_gof[len(exposed) + index]) or 0.0
            measurements.append(MetricMeasurement("blank", thickness, goodness_of_fit))
        return tuple(measurements)

    for index in range(max(len(raw_exposed), len(raw_blank), len(raw_gof))):
        exposed_value = _optional_float(raw_exposed[index]) if index < len(raw_exposed) else None
        blank_value = _optional_float(raw_blank[index]) if index < len(raw_blank) else None
        goodness_of_fit = _optional_float(raw_gof[index]) if index < len(raw_gof) else None
        if exposed_value is not None:
            measurements.append(MetricMeasurement("exposed", exposed_value, goodness_of_fit or 0.0))
        elif blank_value is not None:
            measurements.append(MetricMeasurement("blank", blank_value, goodness_of_fit or 0.0))
    return tuple(measurements)


def _metrics_for_entry(
    entry: Any,
    resources: tuple[RegisteredResource, ...],
    config: ExperimentBrowserConfig,
) -> ExperimentMetrics:
    resource_types = {resource.name: resource.resource_type for resource in resources}
    if "ellipsometry.json" not in resource_types:
        return ExperimentMetrics((), None, None, None, False, None)
    metrics_resource = next(resource for resource in resources if resource.name == "ellipsometry.json")
    if not metrics_resource.available:
        return ExperimentMetrics((), None, None, None, True, metrics_resource.error)
    try:
        raw_data = _read_registered_json(entry, resource_types, "ellipsometry.json", config)
        measurements = _normalized_metrics(raw_data)
    except (ExperimentIntegrityError, ValueError) as exc:
        return ExperimentMetrics((), None, None, None, True, str(exc))
    exposed_average = _metric_average(measurements, "exposed")
    blank_average = _metric_average(measurements, "blank")
    percent_development = (
        (1.0 - (exposed_average / blank_average)) * 100.0
        if exposed_average is not None and blank_average not in (None, 0.0)
        else None
    )
    return ExperimentMetrics(
        measurements=measurements,
        exposed_average_nm=exposed_average,
        blank_average_nm=blank_average,
        percent_development=percent_development,
        degraded=False,
        error=None,
    )


class ExperimentBrowserRepository:
    """Thread-affine access to indexed experiment records and terminal graph repairs."""

    def __init__(
        self,
        config: ExperimentBrowserConfig,
        *,
        reader_factory: ExperimentReaderFactory = ExperimentReader,
        snapshot_analyzer: SnapshotAnalyzer = analyze_registered_snapshot,
    ) -> None:
        self.config = config
        self._reader_factory = reader_factory
        self._snapshot_analyzer = snapshot_analyzer
        self._commands: queue.Queue[_Command | object] = queue.Queue()
        self._stop_token = object()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()
        self._analysis_cache: dict[tuple[Path, ...], _CachedAnalysis] = {}
        self._analysis_locks: dict[tuple[Path, ...], threading.Lock] = {}
        self._analysis_cache_lock = threading.Lock()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="chamber-webview-experiments", daemon=True)
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
            raise TimeoutError("Timed out while stopping the experiment browser repository.")
        with self._lifecycle_lock:
            self._thread = None

    def list_page(
        self,
        filters: ExperimentFilters | None = None,
        *,
        page: int = 1,
        page_size: int | None = None,
    ) -> ExperimentPage:
        selected_filters = filters or ExperimentFilters()
        selected_page_size = self.config.default_page_size if page_size is None else page_size
        self._validate_page(page, selected_page_size)
        return self._invoke(
            lambda reader: self._list_page(reader, selected_filters, page=page, page_size=selected_page_size)
        )

    def get_filter_options(self) -> ExperimentFilterOptions:
        return self._invoke(self._get_filter_options)

    def get_detail(self, run_id: UUID) -> ExperimentDetail:
        if not isinstance(run_id, UUID):
            raise ValueError("Exposure run ID must be a UUID.")
        record = self._invoke(lambda reader: self._find_record(reader, run_id))
        return self._get_detail(record)

    def create_export(self, run_id: UUID) -> ExperimentExportArchive:
        if not isinstance(run_id, UUID):
            raise ValueError("Exposure run ID must be a UUID.")
        record = self._invoke(lambda reader: self._find_record(reader, run_id))
        detail = self._get_detail(record)
        entry = record.get_record()
        return build_experiment_zip(
            _entry_folder_path(self.config.data_path, entry),
            detail,
            max_input_bytes=self.config.export_max_input_bytes,
            retry_attempts=self.config.resource_retry_attempts,
            retry_delay=self.config.resource_retry_delay,
        )

    def open_resource(self, run_id: UUID, name: str) -> OpenResource:
        if not isinstance(run_id, UUID):
            raise ValueError("Exposure run ID must be a UUID.")
        _validate_resource_name(name)
        record = self._invoke(lambda reader: self._find_record(reader, run_id))
        return self._open_resource(record, name)

    def get_metrics(self, run_id: UUID) -> ExperimentMetrics:
        if not isinstance(run_id, UUID):
            raise ValueError("Exposure run ID must be a UUID.")
        record = self._invoke(lambda reader: self._find_record(reader, run_id))
        return self._get_metrics(record)

    def get_event_timeline(self, run_id: UUID) -> ExposureEventTimeline:
        if not isinstance(run_id, UUID):
            raise ValueError("Exposure run ID must be a UUID.")
        record = self._invoke(lambda reader: self._find_record(reader, run_id))
        try:
            event_data = _run_event_data(record)
        except ValueError as exc:
            raise ExperimentIntegrityError(f"Run event journal is invalid: {exc}") from exc
        events = tuple(sorted(event_data.timeline.events, key=lambda event: (event.producer_unix_ns, str(event.event_id))))
        return ExposureEventTimeline(
            run_id=run_id,
            events=tuple(_exposure_event(event) for event in events),
            complete=event_data.timeline.complete,
            issues=_timeline_issue_text(event_data.timeline),
            wall_time_origin_unix_ns=event_data.wall_time_origin_unix_ns,
        )

    def get_run_dose_series(
        self,
        run_id: UUID,
        *,
        time_mode: str = "runtime",
        resolution: str = "full",
    ) -> RunDoseSeries:
        if not isinstance(run_id, UUID):
            raise ValueError("Exposure run ID must be a UUID.")
        if time_mode not in {"runtime", "wall"}:
            raise ValueError("Run dose-series time mode must be runtime or wall.")
        if resolution not in {"full", "thumbnail"}:
            raise ValueError("Run dose-series resolution must be full or thumbnail.")
        record = self._invoke(lambda reader: self._find_record(reader, run_id))
        return self._read_persisted_run_dose_series(run_id, record, time_mode=time_mode, resolution=resolution)

    def get_observer_dose_comparison(
        self,
        run_id: UUID,
        *,
        resolution: str = "full",
    ) -> ObserverDoseComparison:
        if not isinstance(run_id, UUID):
            raise ValueError("Exposure run ID must be a UUID.")
        if resolution not in {"full", "thumbnail"}:
            raise ValueError("Observer dose-series resolution must be full or thumbnail.")
        record = self._invoke(lambda reader: self._find_record(reader, run_id))
        entry = record.get_record()
        try:
            products = load_observer_dose_products(entry, self.config.data_path, run_id)
        except ValueError as exc:
            raise ExperimentIntegrityError(f"Observer dose products are invalid: {exc}") from exc
        if not products:
            return ObserverDoseComparison(run_id, "missing", (), (), resolution, "unavailable")
        try:
            event_data = _run_event_data(record)
            wall_origin = event_data.wall_time_origin_unix_ns
        except ValueError:
            wall_origin = None
        if wall_origin is None:
            wall_origin = min(
                int((product.graph.full if resolution == "full" else product.graph.thumbnail).wall_unix_ns[0])
                for product in products
            )
            wall_origin_quality = "observer_first_capture"
            alignment_issue = (
                "Observer wall time starts at the first observer capture because PREINIT timing is unavailable.",
            )
        else:
            wall_origin_quality = "run_preinit"
            alignment_issue = ()
        series = []
        for product in products:
            analysis = product.analysis
            level = product.graph.full if resolution == "full" else product.graph.thumbnail
            points = tuple(
                ObserverDosePoint(
                    wall_elapsed_seconds=max(0.0, (int(level.wall_unix_ns[index]) - wall_origin) / 1e9),
                    dose_increment_mj_cm2=float(level.dose_increment_mj_cm2[index]),
                    cumulative_dose_mj_cm2=float(level.cumulative_dose_mj_cm2[index]),
                    source_sequence=(
                        None if int(level.source_sequence[index]) < 0 else int(level.source_sequence[index])
                    ),
                    represented_pulse_count=int(level.represented_pulse_count[index]),
                )
                for index in range(level.point_count)
            )
            completeness = analysis.completeness
            series.append(
                ObserverDoseSeries(
                    session_id=analysis.session_id,
                    source_kind=analysis.source_key.source_kind,
                    source_id=analysis.source_key.source_id,
                    algorithm=analysis.algorithm,
                    algorithm_version=analysis.algorithm_version,
                    status=analysis.status,
                    points=points,
                    raw_point_count=product.graph.raw_point_count,
                    pulse_count=analysis.pulse_count,
                    transfer_count=analysis.transfer_count,
                    total_dose_mj_cm2=analysis.total_dose_mj_cm2,
                    average_pulse_dose_mj_cm2=analysis.average_pulse_dose_mj_cm2,
                    calibration_profile_id=analysis.calibration.profile_id,
                    calibration_revision=analysis.calibration.revision,
                    calibration_name=analysis.calibration.name,
                    calibration_hash=analysis.calibration.content_hash,
                    completeness=ObserverDoseCompleteness(**completeness.to_dict()),
                    issues=analysis.issues + alignment_issue,
                )
            )
        series.sort(
            key=lambda item: (
                item.source_kind,
                item.source_id,
                str(item.session_id),
                0 if item.algorithm == "captured" else 1,
            )
        )
        return ObserverDoseComparison(
            run_id,
            "complete",
            tuple(series),
            (),
            resolution,
            wall_origin_quality,
        )

    def ensure_run_dose_series(
        self,
        run_id: UUID,
        *,
        time_mode: str = "runtime",
        resolution: str = "full",
    ) -> RunDoseSeries:
        if not isinstance(run_id, UUID):
            raise ValueError("Exposure run ID must be a UUID.")
        if time_mode not in {"runtime", "wall"}:
            raise ValueError("Run dose-series time mode must be runtime or wall.")
        if resolution not in {"full", "thumbnail"}:
            raise ValueError("Run dose-series resolution must be full or thumbnail.")
        try:
            record, result = self._invoke(
                lambda reader: self._ensure_persisted_run_dose_series(reader, run_id)
            )
        except ExposureGraphError as exc:
            return self._unavailable_run_dose_series(run_id, "error", time_mode, resolution, error=str(exc))
        if result.graph is None:
            return self._unavailable_run_dose_series(run_id, result.status, time_mode, resolution)
        return self._project_persisted_graph(result.graph, record, time_mode=time_mode, resolution=resolution)

    def _ensure_persisted_run_dose_series(self, reader: ExperimentReaderLike, run_id: UUID):
        record = self._find_record(reader, run_id)
        return record, ensure_exposure_graph(run_id, record.get_record(), self.config.data_path)

    @staticmethod
    def _unavailable_run_dose_series(
        run_id: UUID,
        status: str,
        time_mode: str,
        resolution: str,
        *,
        error: str | None = None,
    ) -> RunDoseSeries:
        return RunDoseSeries(
            run_id=run_id,
            status=status,
            points=(),
            errors=() if error is None else (error,),
            source="persisted",
            resolution=resolution,
            raw_pulse_count=0,
            runtime_basis=None,
            time_mode=time_mode,
        )

    def _read_persisted_run_dose_series(
        self,
        run_id: UUID,
        record: Any,
        *,
        time_mode: str,
        resolution: str,
    ) -> RunDoseSeries:
        try:
            graph = read_exposure_graph(record.get_record(), self.config.data_path, run_id)
        except FileNotFoundError:
            return self._unavailable_run_dose_series(run_id, "missing", time_mode, resolution)
        except ExposureGraphValidationError as exc:
            return self._unavailable_run_dose_series(run_id, "error", time_mode, resolution, error=str(exc))
        return self._project_persisted_graph(graph, record, time_mode=time_mode, resolution=resolution)

    @staticmethod
    def _project_persisted_graph(
        graph: ExposureGraph,
        record: Any,
        *,
        time_mode: str,
        resolution: str,
    ) -> RunDoseSeries:
        level = graph.full if resolution == "full" else graph.thumbnail
        points = tuple(
            RunDosePoint(
                wall_elapsed_seconds=float(level.wall_elapsed_seconds[index]),
                runtime_seconds=float(level.runtime_seconds[index]),
                dose_increment_mj_cm2=float(level.dose_increment_mj_cm2[index]),
                cumulative_dose_mj_cm2=float(level.cumulative_dose_mj_cm2[index]),
                dose_rate_mj_cm2_s=(
                    0.0
                    if index == 0 or level.runtime_seconds[index] <= level.runtime_seconds[index - 1]
                    else float(level.dose_increment_mj_cm2[index] / (level.runtime_seconds[index] - level.runtime_seconds[index - 1]))
                ),
                source_index=int(level.source_index[index]),
                source_sequence=None if level.source_sequence[index] < 0 else int(level.source_sequence[index]),
                represented_pulse_count=int(level.represented_pulse_count[index]),
            )
            for index in range(level.point_count)
        )
        try:
            event_data = _run_event_data(record)
            event_issues = _timeline_issue_text(event_data.timeline)
        except ValueError as exc:
            event_data = None
            event_issues = (f"Run event journal is invalid: {exc}",)
        final_runtime = points[-1].runtime_seconds if points else 0.0
        final_wall = None
        if event_data is not None and event_data.wall_time_origin_unix_ns is not None and points:
            final_wall = event_data.wall_time_origin_unix_ns + int(points[-1].wall_elapsed_seconds * 1e9)
        annotations = (
            ()
            if event_data is None
            else _run_annotations(
                event_data,
                time_mode=time_mode,
                final_runtime_seconds=final_runtime,
                final_wall_unix_ns=final_wall,
            )
        )
        issues = event_issues + graph.issues
        if time_mode == "wall" and graph.wall_origin_quality != "run_preinit":
            issues += ("Wall time is measured from the first captured pulse because PREINIT timing is unavailable.",)
        return RunDoseSeries(
            run_id=graph.run_id,
            status="complete",
            points=points,
            errors=(),
            source="persisted",
            resolution=resolution,
            raw_pulse_count=graph.raw_pulse_count,
            runtime_basis=graph.runtime_basis,
            time_mode=time_mode,
            annotations=annotations,
            issues=issues,
        )

    def get_snapshot_analysis(self, run_id: UUID, snapshot_id: UUID) -> SnapshotAnalysisSummary:
        if not isinstance(run_id, UUID) or not isinstance(snapshot_id, UUID):
            raise ValueError("Exposure run and snapshot IDs must be UUIDs.")
        record = self._invoke(lambda reader: self._find_record(reader, run_id))
        paths = self._resolve_snapshot_paths(record, snapshot_id)
        result = self._get_cached_snapshot_analysis(paths)
        return self._snapshot_analysis_summary(result)

    def get_snapshot_series(
        self,
        run_id: UUID,
        snapshot_id: UUID,
        series: str,
        *,
        rolling_window: int = 1,
        time_mode: str = "wall",
    ) -> SnapshotGraphSeries:
        if not isinstance(run_id, UUID) or not isinstance(snapshot_id, UUID):
            raise ValueError("Exposure run and snapshot IDs must be UUIDs.")
        if series not in {"voltage", "peaks", "dose"}:
            raise ValueError("Snapshot series must be voltage, peaks, or dose.")
        if time_mode not in {"wall", "apparent"}:
            raise ValueError("Snapshot time mode must be wall or apparent.")
        allowed_windows = {1} if series == "voltage" else {1, 10, 50, 100}
        if rolling_window not in allowed_windows:
            raise ValueError(f"Rolling window {rolling_window} is not valid for {series} series.")
        record = self._invoke(lambda reader: self._find_record(reader, run_id))
        paths = self._resolve_snapshot_paths(record, snapshot_id)
        try:
            event_data = _run_event_data(record)
            event_issues = _timeline_issue_text(event_data.timeline)
        except ValueError as exc:
            event_data = None
            event_issues = (f"Run event journal is invalid: {exc}",)
        if series == "voltage":
            loader = load_hdf5_voltage_points if paths.snapshot_format == "euv_hdf5" else load_voltage_points
            times, volts = self._run_snapshot_operation(lambda: loader(paths.waveform, time_mode=time_mode))
            if len(times) > self.config.waveform_max_points:
                raise ExperimentResponseTooLarge(
                    f"Snapshot contains {len(times)} points; the response limit is {self.config.waveform_max_points}."
                )
            x = tuple(float(value) for value in times)
            y = tuple(float(value) for value in volts)
            x_label = "Apparent time (s)" if time_mode == "apparent" else "Time (s)"
            y_label = "Voltage (V)"
        else:
            result = self._get_cached_snapshot_analysis(paths)
            analysis = result.analysis
            if series == "peaks":
                first_time = float(analysis.pulse_times_seconds[0]) if len(analysis.pulse_times_seconds) else 0.0
                x = tuple(float(value) - first_time for value in analysis.pulse_times_seconds)
                y = _rolling_average(analysis.pulse_peaks_volts, rolling_window)
                x_label, y_label = "Pulse time (s)", "Peak voltage (V)"
            else:
                x = tuple(float(index) for index in range(1, len(analysis.pulse_doses_mj_cm2) + 1))
                y = _rolling_average(analysis.pulse_doses_mj_cm2, rolling_window)
                x_label, y_label = "Pulse index", "Dose per pulse (mJ/cm²)"
        return SnapshotGraphSeries(
            snapshot_id=snapshot_id,
            series=series,
            x_label=x_label,
            y_label=y_label,
            x=x,
            y=y,
            point_count=len(x),
            rolling_window=rolling_window,
            annotations=(
                ()
                if event_data is None
                else self._snapshot_annotations(event_data, paths, series, time_mode, x)
            ),
            issues=event_issues,
        )

    def _snapshot_annotations(
        self,
        event_data: _RunEventData,
        paths: _SnapshotPaths,
        series: str,
        time_mode: str,
        x_values: tuple[float, ...],
    ) -> tuple[GraphAnnotation, ...]:
        if paths.snapshot_format != "euv_hdf5" or not x_values:
            return ()
        try:
            from euv_acquisition.snapshot import read_snapshot

            contents = self._run_snapshot_operation(lambda: read_snapshot(paths.waveform))
        except ExperimentResourceUnavailable:
            return ()
        timestamps = tuple(int(value) for value in contents.captured_at_unix_ns)
        sequences = tuple(int(value) for value in contents.sequence)
        if not timestamps or len(timestamps) != len(sequences):
            return ()
        first_timestamp = timestamps[0]
        final_timestamp = timestamps[-1]
        maximum_x = x_values[-1]

        def next_pulse_index(timestamp: int) -> int | None:
            for index, captured_at in enumerate(timestamps):
                if captured_at >= timestamp:
                    return index
            return None

        def pulse_x(index: int) -> float:
            if series == "peaks":
                return (timestamps[index] - first_timestamp) / 1e9
            if series == "dose":
                return float(index + 1)
            if time_mode == "wall":
                return (timestamps[index] - first_timestamp) / 1e9
            sample_count = int(contents.samples_v.shape[1])
            return index * max(0, sample_count - 1) / contents.capture_config.sample_rate_hz

        annotations: list[GraphAnnotation] = []
        state_events: dict[str, list[tuple[RunEvent, float, str]]] = {"triggers": [], "transmitting": []}
        for event in event_data.timeline.events:
            category = _annotation_category(event)
            if category is None:
                continue
            if category == "lifecycle":
                if first_timestamp <= event.producer_unix_ns <= final_timestamp:
                    annotations.append(
                        GraphAnnotation(
                            event.event_id,
                            category,
                            "point",
                            _annotation_label(event),
                            (event.producer_unix_ns - first_timestamp) / 1e9,
                            None,
                            None,
                            event.stream_name,
                            event.producer_unix_ns,
                            "producer",
                        )
                    )
                continue
            if event.producer_unix_ns > final_timestamp:
                continue
            index = next_pulse_index(event.producer_unix_ns)
            if index is None:
                continue
            quality = "exact" if timestamps[index] == event.producer_unix_ns else "next_pulse"
            state_events[category].append((event, pulse_x(index), quality))

        for category, items in state_events.items():
            previous = [item for item in items if item[0].producer_unix_ns < first_timestamp]
            visible = [item for item in items if item[0].producer_unix_ns >= first_timestamp]
            if previous:
                visible.insert(0, (previous[-1][0], x_values[0], previous[-1][2]))
            for index, (event, x, quality) in enumerate(visible):
                next_x = visible[index + 1][1] if index + 1 < len(visible) else maximum_x
                if next_x < x:
                    continue
                annotations.append(
                    GraphAnnotation(
                        event.event_id,
                        category,
                        "interval",
                        _annotation_label(event),
                        x,
                        next_x,
                        bool(event.payload.get("value")),
                        event.stream_name,
                        event.producer_unix_ns,
                        quality,
                    )
                )
        return tuple(sorted(annotations, key=lambda item: (item.x, str(item.event_id))))

    def _get_cached_snapshot_analysis(self, paths: _SnapshotPaths) -> AnalyzedSnapshot:
        key = tuple(
            path.resolve()
            for path in (paths.waveform, paths.metadata, paths.calibration)
            if path is not None
        )
        with self._analysis_cache_lock:
            analysis_lock = self._analysis_locks.setdefault(key, threading.Lock())
        with analysis_lock:
            signature = self._snapshot_signature(paths)
            with self._analysis_cache_lock:
                cached = self._analysis_cache.get(key)
                if cached is not None and cached.signature == signature:
                    return cached.result
            if paths.snapshot_format == "euv_hdf5":
                assert paths.calibration is not None
                result = self._run_snapshot_operation(lambda: analyze_hdf5_snapshot(paths.waveform, paths.calibration))
            else:
                assert paths.metadata is not None
                result = self._run_snapshot_operation(lambda: self._snapshot_analyzer(paths.waveform, paths.metadata))
            final_signature = self._snapshot_signature(paths)
            with self._analysis_cache_lock:
                self._analysis_cache[key] = _CachedAnalysis(final_signature, result)
            return result

    def _snapshot_signature(self, paths: _SnapshotPaths) -> tuple[tuple[int, int], ...]:
        try:
            signatures = []
            for path in (paths.waveform, paths.metadata, paths.calibration):
                if path is None:
                    continue
                stat_result = _retry_io(
                    path.stat,
                    attempts=self.config.resource_retry_attempts,
                    delay=self.config.resource_retry_delay,
                )
                signatures.append((stat_result.st_mtime_ns, stat_result.st_size))
        except OSError as exc:
            raise ExperimentResourceUnavailable("Snapshot resources are currently unavailable.") from exc
        return tuple(signatures)

    def _run_snapshot_operation(self, operation: Callable[[], Any]) -> Any:
        for attempt in range(1, self.config.resource_retry_attempts + 1):
            try:
                return operation()
            except SnapshotResourceUnavailable as exc:
                if attempt == self.config.resource_retry_attempts:
                    raise ExperimentResourceUnavailable(
                        f"Snapshot resources remain unavailable after {attempt} attempts."
                    ) from exc
                if self.config.resource_retry_delay:
                    time.sleep(self.config.resource_retry_delay)
            except (SnapshotMetadataError, SnapshotMetadataConflict) as exc:
                raise ExperimentIntegrityError(str(exc)) from exc
        raise AssertionError("Snapshot retry loop exited unexpectedly.")

    def _list_page(
        self,
        reader: ExperimentReaderLike,
        filters: ExperimentFilters,
        *,
        page: int,
        page_size: int,
    ) -> ExperimentPage:
        query = _library_filters(filters)
        total_count = reader.count(query)
        total_pages = ExperimentPage.total_pages_for(total_count, page_size)
        if total_pages and page > total_pages:
            raise ValueError("Exposure page is outside the matching result set.")
        records = reader.query(query, limit=page_size, offset=(page - 1) * page_size)
        return ExperimentPage(
            page=page,
            page_size=page_size,
            total_count=total_count,
            total_pages=total_pages,
            filters=filters,
            items=tuple(_list_item_from_record(record) for record in records),
        )

    def _get_filter_options(self, reader: ExperimentReaderLike) -> ExperimentFilterOptions:
        records = reader.query({}, limit=None)
        actual_doses = []
        target_doses = []
        runtimes = []
        created = []
        for record in records:
            entry = record.get_record()
            if entry is None:
                continue
            tags = entry.get_tags() or {}
            for values, value in (
                (actual_doses, _tag_float(tags, "dose")),
                (target_doses, _tag_float(tags, "target_dose")),
                (runtimes, _tag_float(tags, "runtime")),
            ):
                if value is not None:
                    values.append(value)
            timestamp = _optional_float(entry.get_timestamp())
            if timestamp is not None:
                created.append(timestamp)

        def bounds(values: list[float]) -> tuple[float | None, float | None]:
            return (min(values), max(values)) if values else (None, None)

        actual_dose_min, actual_dose_max = bounds(actual_doses)
        target_dose_min, target_dose_max = bounds(target_doses)
        runtime_min, runtime_max = bounds(runtimes)
        created_min, created_max = bounds(created)
        samples, zr_filters, operators = self._read_settings_presets()
        return ExperimentFilterOptions(
            samples=samples,
            operators=operators,
            zr_filters=zr_filters,
            actual_dose_min=actual_dose_min,
            actual_dose_max=actual_dose_max,
            target_dose_min=target_dose_min,
            target_dose_max=target_dose_max,
            runtime_min=runtime_min,
            runtime_max=runtime_max,
            created_min=created_min,
            created_max=created_max,
        )

    def _read_settings_presets(self) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        library = Library(self.config.data_path, read_only=True)
        try:
            entries = library.query({"tags": {"settings_presets": None}}, limit=1)
            if not entries:
                return (), (), ()
            entry = entries[0]

            def read_lines(name: str, resource_type: str) -> tuple[str, ...]:
                try:
                    with entry.resource(name, resource_type, "r") as resource:
                        values = {line.strip() for line in resource if line.strip()}
                except FileNotFoundError:
                    return ()
                return tuple(sorted(values, key=str.casefold))

            return (
                read_lines("sample_types.dat", "Sample Types"),
                read_lines("zr_filters.dat", "Zr Filters"),
                read_lines("operators.dat", "Operators"),
            )
        finally:
            library.close()

    @staticmethod
    def _find_record(reader: ExperimentReaderLike, run_id: UUID) -> Any:
        records = reader.query({"tags": {"run": run_id.hex}}, limit=2)
        if not records:
            raise ExperimentNotFoundError("Exposure run was not found.")
        if len(records) != 1:
            raise ExperimentIntegrityError("Multiple indexed entries share one experiment run UUID.")
        return records[0]

    def _get_detail(self, record: Any) -> ExperimentDetail:
        summary = _list_item_from_record(record)
        entry = record.get_record()
        issues: list[ExperimentDataIssue] = []
        try:
            resources = _registered_resources(entry, self.config)
        except ExperimentResourceUnavailable as exc:
            resources = ()
            issues.append(ExperimentDataIssue("registry", "registry.dat", "unavailable", str(exc)))
        except OSError as exc:
            resources = ()
            issues.append(
                ExperimentDataIssue(
                    "registry",
                    "registry.dat",
                    "unavailable",
                    _unavailable_message("registry.dat", self.config.resource_retry_attempts, exc),
                )
            )
        except ExperimentIntegrityError as exc:
            resources = ()
            issues.append(ExperimentDataIssue("registry", "registry.dat", "integrity", str(exc)))
        issues.extend(
            ExperimentDataIssue(
                "resources",
                resource.name,
                "unavailable",
                resource.error or f"Registered resource {resource.name!r} is unavailable.",
            )
            for resource in resources
            if not resource.available
        )
        resource_types = {resource.name: resource.resource_type for resource in resources}
        run_state = self._read_detail_json(entry, resource_types, "run.json", issues, required=True)
        metadata = self._read_detail_json(entry, resource_types, "metadata.json", issues, required=True) or {}
        end_metadata = self._read_detail_json(entry, resource_types, "end_metadata.json", issues)
        try:
            settings = _settings_from_run_state(run_state)
        except ExperimentIntegrityError as exc:
            settings = {}
            issues.append(ExperimentDataIssue("settings", "run.json", "malformed", str(exc)))
        snapshots, snapshot_issues = _canonical_snapshot_inventory(entry, resources)
        issues.extend(snapshot_issues)
        try:
            capture_timeline = _capture_timeline_points(entry, resources, self.config)
        except (ExperimentIntegrityError, ExperimentResourceUnavailable) as exc:
            capture_timeline = {}
            issues.append(ExperimentDataIssue("snapshots", _CAPTURE_TIMELINE_RESOURCE, "integrity", str(exc)))
        snapshots = tuple(
            replace(snapshot, final_sequence=capture_timeline[snapshot.snapshot_id].final_sequence)
            if snapshot.snapshot_id in capture_timeline
            else snapshot
            for snapshot in snapshots
        )
        tags = entry.get_tags() or {}
        normalized_tags = {
            str(key): value if isinstance(value, (str, float)) else str(value)
            for key, value in tags.items()
        }
        ended_at = _optional_float((end_metadata or {}).get("end_time"))
        event_id = _optional_text(metadata.get("event_uuid")) or str(summary.run_id)
        return ExperimentDetail(
            summary=summary,
            settings=settings,
            metadata=metadata,
            end_metadata=end_metadata,
            tags=normalized_tags,
            resources=resources,
            snapshots=snapshots,
            metrics=_metrics_for_entry(entry, resources, self.config),
            log_range=LogRangeSummary(
                event_id=event_id,
                created_at=_optional_float(metadata.get("created_at")) or summary.created_at,
                ended_at=ended_at,
                complete=end_metadata is not None,
            ),
            issues=tuple(issues),
        )

    def _read_detail_json(
        self,
        entry: Any,
        resource_types: dict[str, str],
        name: str,
        issues: list[ExperimentDataIssue],
        *,
        required: bool = False,
    ) -> dict[str, Any] | None:
        if name not in resource_types:
            if required:
                issues.append(
                    ExperimentDataIssue(
                        name.removesuffix(".json"),
                        name,
                        "missing",
                        f"Expected resource {name!r} is not registered.",
                    )
                )
            return None
        try:
            return _read_registered_json(entry, resource_types, name, self.config)
        except ExperimentIntegrityError as exc:
            kind = "unavailable" if isinstance(exc.__cause__, OSError) else "malformed"
            issues.append(
                ExperimentDataIssue(name.removesuffix(".json"), name, kind, str(exc))
            )
            return None

    def _get_metrics(self, record: Any) -> ExperimentMetrics:
        entry = record.get_record()
        try:
            resources = _registered_resources(entry, self.config)
        except (OSError, ExperimentIntegrityError, ExperimentResourceUnavailable) as exc:
            return ExperimentMetrics((), None, None, None, True, f"Exposure registry is unavailable or invalid: {exc}")
        return _metrics_for_entry(entry, resources, self.config)

    def _resolve_snapshot_paths(
        self,
        record: Any,
        snapshot_id: UUID,
    ) -> _SnapshotPaths:
        entry = record.get_record()
        resources = _registered_resources(entry, self.config)
        snapshots, snapshot_issues = _canonical_snapshot_inventory(entry, resources)
        if snapshot_issues:
            raise ExperimentIntegrityError(" ".join(issue.message for issue in snapshot_issues))
        snapshot = next((candidate for candidate in snapshots if candidate.snapshot_id == snapshot_id), None)
        if snapshot is None:
            raise ExperimentNotFoundError("Exposure snapshot was not found.")
        return self._snapshot_paths(entry, resources, snapshot)

    def _snapshot_paths(
        self,
        entry: Any,
        resources: tuple[RegisteredResource, ...],
        snapshot: SnapshotSummary,
    ) -> _SnapshotPaths:
        required_resources = [snapshot.waveform]
        if snapshot.metadata is not None:
            required_resources.append(snapshot.metadata)
        calibration_path = None
        if snapshot.snapshot_format == "euv_hdf5":
            calibration_resource = next(
                (
                    resource
                    for resource in resources
                    if resource.name == _CALIBRATION_PROVENANCE_RESOURCE
                    and resource.resource_type == _CALIBRATION_PROVENANCE_RESOURCE_TYPE
                ),
                None,
            )
            if calibration_resource is None:
                raise ExperimentIntegrityError(
                    "Native HDF5 snapshots require the registered EUV calibration provenance resource."
                )
            required_resources.append(calibration_resource)
            calibration_path = _resource_path(self.config.data_path, entry, calibration_resource.name)
        unavailable = [resource.name for resource in required_resources if not resource.available]
        if unavailable:
            raise ExperimentResourceUnavailable(
                f"Registered snapshot resources are currently unavailable: {', '.join(unavailable)}."
            )
        return _SnapshotPaths(
            waveform=_resource_path(self.config.data_path, entry, snapshot.waveform.name),
            metadata=None if snapshot.metadata is None else _resource_path(self.config.data_path, entry, snapshot.metadata.name),
            snapshot_format=snapshot.snapshot_format,
            calibration=calibration_path,
        )

    @staticmethod
    def _snapshot_analysis_summary(result: AnalyzedSnapshot) -> SnapshotAnalysisSummary:
        analysis = result.analysis
        return SnapshotAnalysisSummary(
            average_pulse_dose_mj_cm2=analysis.average_pulse_dose_mj_cm2,
            total_dose_mj_cm2=result.total_dose_mj_cm2,
            delivered_dose_rate_mj_cm2_s=analysis.delivered_dose_rate_mj_cm2_s,
            pulse_span_seconds=analysis.pulse_span_seconds,
            wall_duration_seconds=analysis.wall_duration_seconds,
            effective_duration_seconds=analysis.effective_duration_seconds,
            runtime_contribution_seconds=analysis.runtime_contribution_seconds,
            is_step_exposure=analysis.is_step_exposure,
            step_mode_source=result.step_mode_source,
            metadata_backfilled=result.metadata_backfilled,
            backfill_error=result.backfill_error,
        )

    def _open_resource(self, record: Any, name: str) -> OpenResource:
        entry = record.get_record()
        try:
            resources = _registered_resources(entry, self.config)
        except OSError as exc:
            raise ExperimentResourceUnavailable(
                _unavailable_message("registry.dat", self.config.resource_retry_attempts, exc)
            ) from exc
        selected = next((resource for resource in resources if resource.name == name), None)
        if selected is None:
            raise ExperimentNotFoundError("Exposure resource was not found.")
        try:
            path = _resource_path(self.config.data_path, entry, name)
            resource_file = _retry_io(
                lambda: path.open("rb"),
                attempts=self.config.resource_retry_attempts,
                delay=self.config.resource_retry_delay,
            )
            resource_file.seek(0, os.SEEK_END)
            size_bytes = resource_file.tell()
            resource_file.seek(0)
        except OSError as exc:
            raise ExperimentResourceUnavailable(
                _unavailable_message(name, self.config.resource_retry_attempts, exc)
            ) from exc
        return OpenResource(
            RegisteredResource(name, selected.resource_type, size_bytes, True, True, None),
            resource_file,
        )

    def _validate_page(self, page: int, page_size: int) -> None:
        if not isinstance(page, int) or page < 1:
            raise ValueError("Exposure page must be a positive integer.")
        if page_size not in self.config.allowed_page_sizes:
            choices = ", ".join(str(size) for size in self.config.allowed_page_sizes)
            raise ValueError(f"Exposure page size must be one of: {choices}.")

    def _invoke(self, operation: Callable[[ExperimentReaderLike], Any]) -> Any:
        with self._lifecycle_lock:
            if self._thread is None or not self._thread.is_alive():
                raise RuntimeError("Exposure browser repository is not running.")
        response: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)
        self._commands.put(_Command(operation=operation, response=response))
        succeeded, result = response.get()
        if succeeded:
            return result
        raise result

    def _run(self) -> None:
        reader: ExperimentReaderLike | None = None
        try:
            while True:
                command = self._commands.get()
                if command is self._stop_token:
                    return
                assert isinstance(command, _Command)
                try:
                    if reader is None:
                        reader = self._reader_factory(
                            self.config.data_path,
                            self.config.experiment_type,
                            read_only=False,
                        )
                    result = command.operation(reader)
                except Exception as exc:
                    if self._requires_reopen(exc):
                        reader = self._close_reader(reader)
                        unavailable = ExperimentRepositoryUnavailable("Exposure index is temporarily unavailable.")
                        unavailable.__cause__ = exc
                        command.response.put((False, unavailable))
                    else:
                        command.response.put((False, exc))
                else:
                    command.response.put((True, result))
        finally:
            self._close_reader(reader)

    @staticmethod
    def _requires_reopen(exc: Exception) -> bool:
        return isinstance(exc, (OSError, sqlite3.Error))

    @staticmethod
    def _close_reader(reader: ExperimentReaderLike | None) -> None:
        if reader is not None:
            try:
                reader.close()
            except Exception:
                pass
        return None