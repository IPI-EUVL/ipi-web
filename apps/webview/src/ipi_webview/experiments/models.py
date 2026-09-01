from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ExperimentBrowserConfig:
    data_path: str
    experiment_type: str = "exposure"
    default_page_size: int = 50
    allowed_page_sizes: tuple[int, ...] = (25, 50, 100)
    resource_retry_attempts: int = 3
    resource_retry_delay: float = 0.25
    snapshot_analysis_workers: int = 12
    waveform_max_points: int = 2_000_000
    export_max_input_bytes: int = 20 * 1024 * 1024 * 1024

    def __post_init__(self) -> None:
        if not self.data_path.strip():
            raise ValueError("Exposure browser data path cannot be empty.")
        if not self.experiment_type.strip():
            raise ValueError("Exposure browser experiment type cannot be empty.")
        if not self.allowed_page_sizes or any(size <= 0 for size in self.allowed_page_sizes):
            raise ValueError("Exposure browser page sizes must be positive.")
        if self.default_page_size not in self.allowed_page_sizes:
            raise ValueError("Exposure browser default page size must be allowed.")
        if self.resource_retry_attempts < 1:
            raise ValueError("Exposure browser resource retry attempts must be positive.")
        if self.resource_retry_delay < 0:
            raise ValueError("Exposure browser resource retry delay cannot be negative.")
        if not 1 <= self.snapshot_analysis_workers <= 20:
            raise ValueError("Exposure browser snapshot analysis workers must be between 1 and 20.")
        if self.waveform_max_points < 1:
            raise ValueError("Exposure browser waveform point limit must be positive.")
        if self.export_max_input_bytes < 1:
            raise ValueError("Exposure browser export byte limit must be positive.")


@dataclass(frozen=True, slots=True)
class ExperimentFilters:
    name: str | None = None
    created_min: float | None = None
    created_max: float | None = None
    min_actual_dose: float | None = None
    max_actual_dose: float | None = None
    min_target_dose: float | None = None
    max_target_dose: float | None = None
    min_runtime: float | None = None
    max_runtime: float | None = None
    zr_filter: str | None = None
    sample: str | None = None
    operator: str | None = None

    def __post_init__(self) -> None:
        if self.created_min is not None and self.created_max is not None and self.created_min > self.created_max:
            raise ValueError("Exposure created_min cannot exceed created_max.")
        if (
            self.min_actual_dose is not None
            and self.max_actual_dose is not None
            and self.min_actual_dose > self.max_actual_dose
        ):
            raise ValueError("Exposure minimum actual dose cannot exceed its maximum.")
        if (
            self.min_target_dose is not None
            and self.max_target_dose is not None
            and self.min_target_dose > self.max_target_dose
        ):
            raise ValueError("Exposure minimum target dose cannot exceed its maximum.")
        if self.min_runtime is not None and self.max_runtime is not None and self.min_runtime > self.max_runtime:
            raise ValueError("Exposure min_runtime cannot exceed max_runtime.")


@dataclass(frozen=True, slots=True)
class ExperimentFilterOptions:
    samples: tuple[str, ...]
    operators: tuple[str, ...]
    zr_filters: tuple[str, ...]
    actual_dose_min: float | None
    actual_dose_max: float | None
    target_dose_min: float | None
    target_dose_max: float | None
    runtime_min: float | None
    runtime_max: float | None
    created_min: float | None
    created_max: float | None


@dataclass(frozen=True, slots=True)
class ExperimentListItem:
    run_id: UUID
    created_at: float
    name: str
    description: str
    sample: str | None
    operator: str | None
    zr_filter: str | None
    target_dose: float | None
    target_time: float | None
    actual_dose: float | None
    runtime: float | None
    effective_dose_rate: float | None
    exposed_thickness_nm: float | None
    blank_thickness_nm: float | None
    percent_development: float | None
    status: str | None
    end_reason: str | None


@dataclass(frozen=True, slots=True)
class ExperimentPage:
    page: int
    page_size: int
    total_count: int
    total_pages: int
    filters: ExperimentFilters
    items: tuple[ExperimentListItem, ...]

    @staticmethod
    def total_pages_for(total_count: int, page_size: int) -> int:
        return ceil(total_count / page_size) if total_count else 0


@dataclass(frozen=True, slots=True)
class RegisteredResource:
    name: str
    resource_type: str
    size_bytes: int | None
    available: bool
    downloadable: bool
    error: str | None


@dataclass(frozen=True, slots=True)
class SnapshotSummary:
    snapshot_id: UUID
    snapshot_format: str
    waveform: RegisteredResource
    metadata: RegisteredResource | None
    final_sequence: int | None = None


@dataclass(frozen=True, slots=True)
class SnapshotAnalysisSummary:
    average_pulse_dose_mj_cm2: float
    total_dose_mj_cm2: float
    delivered_dose_rate_mj_cm2_s: float
    pulse_span_seconds: float
    wall_duration_seconds: float
    effective_duration_seconds: float
    runtime_contribution_seconds: float
    is_step_exposure: bool
    step_mode_source: str
    metadata_backfilled: bool
    backfill_error: str | None


@dataclass(frozen=True, slots=True)
class SnapshotGraphSeries:
    snapshot_id: UUID
    series: str
    x_label: str
    y_label: str
    x: tuple[float, ...]
    y: tuple[float, ...]
    point_count: int
    rolling_window: int
    annotations: tuple["GraphAnnotation", ...] = ()
    issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GraphAnnotation:
    event_id: UUID
    category: str
    kind: str
    label: str
    x: float
    x_end: float | None
    value: bool | None
    source: str
    producer_unix_ns: int
    projection_quality: str


@dataclass(frozen=True, slots=True)
class ExposureEvent:
    event_id: UUID
    stream_id: UUID
    stream_name: str
    sequence: int
    kind: str
    producer_unix_ns: int
    producer_monotonic_ns: int | None
    ingest_unix_ns: int
    payload: dict[str, Any]
    capture_session_id: UUID | None
    next_sequence: int | None
    runtime_seconds: float | None


@dataclass(frozen=True, slots=True)
class ExposureEventTimeline:
    run_id: UUID
    events: tuple[ExposureEvent, ...]
    complete: bool
    issues: tuple[str, ...]
    wall_time_origin_unix_ns: int | None


@dataclass(frozen=True, slots=True)
class RunDosePoint:
    wall_elapsed_seconds: float
    runtime_seconds: float
    dose_increment_mj_cm2: float
    cumulative_dose_mj_cm2: float
    dose_rate_mj_cm2_s: float
    source_index: int
    source_sequence: int | None
    represented_pulse_count: int


@dataclass(frozen=True, slots=True)
class RunDoseSeries:
    run_id: UUID
    status: str
    points: tuple[RunDosePoint, ...]
    errors: tuple[str, ...]
    source: str
    resolution: str
    raw_pulse_count: int
    runtime_basis: str | None = None
    time_mode: str = "runtime"
    annotations: tuple[GraphAnnotation, ...] = ()
    issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ObserverDosePoint:
    wall_elapsed_seconds: float
    dose_increment_mj_cm2: float
    cumulative_dose_mj_cm2: float
    source_sequence: int | None
    represented_pulse_count: int


@dataclass(frozen=True, slots=True)
class ObserverDoseCompleteness:
    snapshot_count: int
    included_snapshot_count: int
    excluded_snapshot_count: int
    unknown_eligibility_snapshot_count: int
    unknown_step_mode_snapshot_count: int


@dataclass(frozen=True, slots=True)
class ObserverDoseSeries:
    session_id: UUID
    source_kind: str
    source_id: str
    algorithm: str
    algorithm_version: str
    status: str
    points: tuple[ObserverDosePoint, ...]
    raw_point_count: int
    pulse_count: int
    transfer_count: int
    total_dose_mj_cm2: float
    average_pulse_dose_mj_cm2: float
    calibration_profile_id: UUID
    calibration_revision: int
    calibration_name: str
    calibration_hash: str
    completeness: ObserverDoseCompleteness
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ObserverDoseComparison:
    run_id: UUID
    status: str
    series: tuple[ObserverDoseSeries, ...]
    errors: tuple[str, ...]
    resolution: str
    wall_origin_quality: str


@dataclass(frozen=True, slots=True)
class LogRangeSummary:
    event_id: str
    created_at: float | None
    ended_at: float | None
    complete: bool


@dataclass(frozen=True, slots=True)
class ExperimentDataIssue:
    section: str
    resource_name: str | None
    kind: str
    message: str


@dataclass(frozen=True, slots=True)
class MetricMeasurement:
    spot_type: str
    thickness_nm: float
    goodness_of_fit: float


@dataclass(frozen=True, slots=True)
class ExperimentMetrics:
    measurements: tuple[MetricMeasurement, ...]
    exposed_average_nm: float | None
    blank_average_nm: float | None
    percent_development: float | None
    degraded: bool
    error: str | None


@dataclass(frozen=True, slots=True)
class ExperimentDetail:
    summary: ExperimentListItem
    settings: dict[str, Any]
    metadata: dict[str, Any]
    end_metadata: dict[str, Any] | None
    tags: dict[str, str | float]
    resources: tuple[RegisteredResource, ...]
    snapshots: tuple[SnapshotSummary, ...]
    metrics: ExperimentMetrics
    log_range: LogRangeSummary
    issues: tuple[ExperimentDataIssue, ...]