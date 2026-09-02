from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class HealthState(str, Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    UNKNOWN = "unknown"


class IssueSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


class PublicExperimentPhase(str, Enum):
    CHECKING = "checking_system"
    PREPARING = "preparing"
    INITIALIZING = "initializing"
    EXPOSING = "exposing"
    STOPPING = "stopping"
    IDLE = "idle"


class ProgressMode(str, Enum):
    NONE = "none"
    DOSE = "dose"
    TIME = "time"
    INDETERMINATE = "indeterminate"


class PublicStageState(str, Enum):
    IDLE = "idle"
    HOMING = "homing"
    MOVING = "moving"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class SourceState(str, Enum):
    AVAILABLE = "available"
    NOT_APPLICABLE = "not_applicable"
    DEGRADED = "degraded"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class SystemIssue(ApiModel):
    severity: IssueSeverity
    source: str
    message: str


class SystemSummary(ApiModel):
    state: HealthState
    label: str
    issues: tuple[SystemIssue, ...]


class SourceSummary(ApiModel):
    state: SourceState
    observed_at: float | None
    attempted_at: float | None
    error: str | None


class ExperimentReason(ApiModel):
    subsystem: str
    status: str
    reason: str


class ExperimentDetails(ApiModel):
    run_id: UUID
    name: str
    description: str
    operator: str
    zr_filter: str
    sample_number: int | None = Field(default=None, ge=1)
    sample_type: str
    target_dose: float | None
    target_time: float | None
    base_pressure: float | None
    operating_pressure: float | None
    flow_sccm: float | None


class ExperimentSummary(ApiModel):
    phase: PublicExperimentPhase
    details: ExperimentDetails | None
    reasons: tuple[ExperimentReason, ...]


class ProgressSummary(ApiModel):
    mode: ProgressMode
    current: float | None
    target: float | None
    unit: str | None
    percent: float | None = Field(default=None, ge=0.0, le=100.0)


class QueueSummary(ApiModel):
    remaining_count: int = Field(ge=0)
    current_batch_remaining_count: int = Field(ge=0)


class BatchExposureSummary(ApiModel):
    run_id: UUID | None
    queue_position: int | None = Field(default=None, ge=1)
    created_at: float | None
    name: str
    sample_number: int | None = Field(default=None, ge=1)
    target_dose: float | None
    target_time: float | None
    actual_dose: float | None
    actual_time: float | None
    state: str
    status: str | None
    end_reason: str | None


class BatchSlotSummary(ApiModel):
    sample_number: int = Field(ge=1)
    attempt_count: int = Field(ge=0)
    first_target_dose: float | None
    first_target_time: float | None
    cumulative_actual_dose: float
    cumulative_actual_time: float
    state: str
    abort_reasons: tuple[str, ...]


class BatchPlanEntrySummary(ApiModel):
    order: int = Field(ge=1)
    sample_number: int = Field(ge=1)
    mode: str
    target: float = Field(ge=0)
    cumulative_actual: float | None
    attempt_count: int = Field(ge=0)
    state: str
    remainder: float = Field(ge=0)
    overshoot: float = Field(ge=0)


class BatchSummary(ApiModel):
    name: str | None
    selection_source: str
    exposures: tuple[BatchExposureSummary, ...]
    slots: tuple[BatchSlotSummary, ...]
    unplaced_exposures: tuple[BatchExposureSummary, ...]
    remaining_count: int = Field(ge=0)
    possibly_truncated: bool
    authoritative: bool = False
    batch_id: UUID | None = None
    lease_owned: bool | None = None
    controller_phase: str | None = None
    controller_message: str | None = None
    execution_mode: str | None = None
    manifest_status: str | None = None
    revision: int | None = Field(default=None, ge=1)
    paused: bool | None = None
    cancel_pending: bool | None = None
    decision_kind: str | None = None
    decision_message: str | None = None
    plan_entries: tuple[BatchPlanEntrySummary, ...] = ()


class StagePosition(ApiModel):
    theta: float
    z: float


class StageSummary(ApiModel):
    state: PublicStageState
    current_sample_number: int | None = Field(default=None, ge=1)
    position: StagePosition | None


class SubsystemIssue(ApiModel):
    severity: IssueSeverity
    message: str


class SubsystemSummary(ApiModel):
    name: str
    critical: bool
    connected: bool
    primary_status: str
    issues: tuple[SubsystemIssue, ...]


class LiveResponse(ApiModel):
    schema_version: Literal["1"] = "1"
    revision: int = Field(ge=0)
    generated_at: float
    system: SystemSummary
    experiment: ExperimentSummary
    progress: ProgressSummary
    queue: QueueSummary
    batch: BatchSummary
    stage: StageSummary
    subsystems: tuple[SubsystemSummary, ...]
    sources: dict[str, SourceSummary]


class SubsystemsResponse(ApiModel):
    schema_version: Literal["1"] = "1"
    revision: int = Field(ge=0)
    generated_at: float
    system: SystemSummary
    items: tuple[SubsystemSummary, ...]


class CameraSummary(ApiModel):
    id: str
    name: str
    configured: bool


class CamerasResponse(ApiModel):
    schema_version: Literal["1"] = "1"
    items: tuple[CameraSummary, ...] = ()


class ExperimentFiltersResponse(ApiModel):
    name: str | None
    created_min: float | None
    created_max: float | None
    min_actual_dose: float | None
    max_actual_dose: float | None
    min_target_dose: float | None
    max_target_dose: float | None
    min_runtime: float | None
    max_runtime: float | None
    zr_filter: str | None
    sample: str | None
    operator: str | None


class ExperimentFilterOptionsResponse(ApiModel):
    schema_version: Literal["1"] = "1"
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


class ExperimentListItemResponse(ApiModel):
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


class ExperimentPageResponse(ApiModel):
    schema_version: Literal["1"] = "1"
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_count: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    filters: ExperimentFiltersResponse
    items: tuple[ExperimentListItemResponse, ...]


class RegisteredResourceResponse(ApiModel):
    name: str
    resource_type: str
    size_bytes: int | None = Field(default=None, ge=0)
    available: bool
    downloadable: bool
    error: str | None


class SnapshotResponse(ApiModel):
    snapshot_id: UUID
    format: Literal["legacy_npz", "euv_hdf5"]
    waveform: RegisteredResourceResponse
    metadata: RegisteredResourceResponse | None
    final_sequence: int | None = Field(default=None, ge=0)


class SnapshotAnalysisResponse(ApiModel):
    schema_version: Literal["1"] = "1"
    average_pulse_dose_mj_cm2: float
    total_dose_mj_cm2: float
    delivered_dose_rate_mj_cm2_s: float
    pulse_span_seconds: float = Field(ge=0)
    wall_duration_seconds: float = Field(ge=0)
    effective_duration_seconds: float = Field(ge=0)
    runtime_contribution_seconds: float = Field(ge=0)
    is_step_exposure: bool
    step_mode_source: Literal["provided", "inferred", "native"]
    metadata_backfilled: bool
    backfill_error: str | None


class GraphAnnotationResponse(ApiModel):
    event_id: UUID
    category: Literal["lifecycle", "triggers", "transmitting"]
    kind: Literal["point", "interval"]
    label: str
    x: float
    x_end: float | None = None
    value: bool | None = None
    source: str
    producer_unix_ns: int = Field(ge=0)
    projection_quality: Literal["producer", "runtime_hint", "exact", "next_pulse"]


class SnapshotGraphSeriesResponse(ApiModel):
    schema_version: Literal["2"] = "2"
    snapshot_id: UUID
    series: Literal["voltage", "peaks", "dose"]
    x_label: str
    y_label: str
    x: tuple[float, ...]
    y: tuple[float, ...]
    point_count: int = Field(ge=0)
    rolling_window: int = Field(ge=1)
    annotations: tuple[GraphAnnotationResponse, ...]
    issues: tuple[str, ...]


class RunDosePointResponse(ApiModel):
    wall_elapsed_seconds: float = Field(ge=0)
    runtime_seconds: float = Field(ge=0)
    dose_increment_mj_cm2: float
    cumulative_dose_mj_cm2: float
    dose_rate_mj_cm2_s: float
    source_index: int
    source_sequence: int | None = None
    represented_pulse_count: int = Field(ge=0)


class RunDoseSeriesResponse(ApiModel):
    schema_version: Literal["3"] = "3"
    run_id: UUID
    status: Literal["waiting_for_completion", "missing", "busy", "complete", "error"]
    points: tuple[RunDosePointResponse, ...]
    errors: tuple[str, ...]
    source: Literal["persisted"]
    resolution: Literal["full", "thumbnail"]
    raw_pulse_count: int = Field(ge=0)
    runtime_basis: str | None = None
    time_mode: Literal["runtime", "wall"]
    annotations: tuple[GraphAnnotationResponse, ...]
    issues: tuple[str, ...]
    source_kind: str | None = None
    source_id: str | None = None


class ObserverDosePointResponse(ApiModel):
    wall_elapsed_seconds: float = Field(ge=0)
    dose_increment_mj_cm2: float
    cumulative_dose_mj_cm2: float
    source_sequence: int | None = None
    represented_pulse_count: int = Field(ge=0)


class ObserverDoseCompletenessResponse(ApiModel):
    snapshot_count: int = Field(ge=0)
    included_snapshot_count: int = Field(ge=0)
    excluded_snapshot_count: int = Field(ge=0)
    unknown_eligibility_snapshot_count: int = Field(ge=0)
    unknown_step_mode_snapshot_count: int = Field(ge=0)


class ObserverDoseSeriesResponse(ApiModel):
    session_id: UUID
    source_kind: str
    source_id: str
    algorithm: Literal["captured", "legacy_compensated"]
    algorithm_version: str
    status: Literal["complete", "incomplete"]
    points: tuple[ObserverDosePointResponse, ...]
    raw_point_count: int = Field(ge=0)
    pulse_count: int = Field(ge=0)
    transfer_count: int = Field(ge=0)
    total_dose_mj_cm2: float
    average_pulse_dose_mj_cm2: float
    calibration_profile_id: UUID
    calibration_revision: int = Field(ge=1)
    calibration_name: str
    calibration_hash: str
    completeness: ObserverDoseCompletenessResponse
    issues: tuple[str, ...]


class ObserverDoseComparisonResponse(ApiModel):
    schema_version: Literal["1"] = "1"
    run_id: UUID
    status: Literal["missing", "complete"]
    series: tuple[ObserverDoseSeriesResponse, ...]
    errors: tuple[str, ...]
    resolution: Literal["full", "thumbnail"]
    wall_origin_quality: Literal["unavailable", "observer_first_capture", "run_preinit"]


class ExposureEventResponse(ApiModel):
    event_id: UUID
    stream_id: UUID
    stream_name: str
    sequence: int = Field(ge=0)
    kind: str
    producer_unix_ns: int = Field(ge=0)
    producer_monotonic_ns: int | None = Field(default=None, ge=0)
    ingest_unix_ns: int = Field(ge=0)
    payload: dict[str, Any]
    capture_session_id: UUID | None = None
    next_sequence: int | None = Field(default=None, ge=0)
    runtime_seconds: float | None = Field(default=None, ge=0)


class ExposureEventTimelineResponse(ApiModel):
    schema_version: Literal["1"] = "1"
    run_id: UUID
    events: tuple[ExposureEventResponse, ...]
    complete: bool
    issues: tuple[str, ...]
    wall_time_origin_unix_ns: int | None = Field(default=None, ge=0)


class LogRangeResponse(ApiModel):
    event_id: str
    created_at: float | None
    ended_at: float | None
    complete: bool


class MetricMeasurementResponse(ApiModel):
    spot_type: Literal["exposed", "blank"]
    thickness_nm: float
    goodness_of_fit: float


class ExperimentMetricsResponse(ApiModel):
    schema_version: Literal["1"] = "1"
    measurements: tuple[MetricMeasurementResponse, ...]
    exposed_average_nm: float | None
    blank_average_nm: float | None
    percent_development: float | None
    degraded: bool
    error: str | None


class ExperimentDataIssueResponse(ApiModel):
    section: str
    resource_name: str | None
    kind: str
    message: str


class ExperimentDetailResponse(ApiModel):
    schema_version: Literal["1"] = "1"
    summary: ExperimentListItemResponse
    settings: dict[str, object]
    metadata: dict[str, object]
    end_metadata: dict[str, object] | None
    tags: dict[str, str | float]
    resources: tuple[RegisteredResourceResponse, ...]
    snapshots: tuple[SnapshotResponse, ...]
    metrics: ExperimentMetricsResponse
    log_range: LogRangeResponse
    issues: tuple[ExperimentDataIssueResponse, ...]


class ExperimentResourcesResponse(ApiModel):
    schema_version: Literal["1"] = "1"
    run_id: UUID
    items: tuple[RegisteredResourceResponse, ...]


class LogFiltersResponse(ApiModel):
    origin_uuid: str | None
    l_type: str | None
    level: str | None
    min_level: str | None
    exclude_types: tuple[str, ...] | None
    line_from: int | None
    line_to: int | None
    since: float | None
    until: float | None


class LogArchiveResponse(ApiModel):
    name: str
    is_current: bool
    start_line: int = Field(ge=0)
    end_line_exclusive: int = Field(ge=0)
    start_timestamp: float | None
    end_timestamp: float | None


class LogArchivesResponse(ApiModel):
    schema_version: Literal["1"] = "1"
    items: tuple[LogArchiveResponse, ...]


class LogEntryResponse(ApiModel):
    line: int = Field(ge=0)
    timestamp: float | None
    origin_uuid: str | None
    l_type: str
    level: str
    subsystem: str
    message: str
    record: dict[str, Any]


class LogPageResponse(ApiModel):
    schema_version: Literal["1"] = "1"
    archive: str
    filters: LogFiltersResponse
    rows: tuple[LogEntryResponse, ...]
    first_line: int | None = Field(default=None, ge=0)
    last_line: int | None = Field(default=None, ge=0)
    has_before: bool
    has_after: bool
    at_tail: bool


class LogEventResponse(ApiModel):
    event_id: str
    e_type: str
    level: str
    message: str
    start_line: int = Field(ge=0)
    end_line: int | None = Field(default=None, ge=0)
    start_timestamp: float | None
    end_timestamp: float | None
    data_start: dict[str, Any]
    data_end: dict[str, Any]


class LogEventsResponse(ApiModel):
    schema_version: Literal["1"] = "1"
    items: tuple[LogEventResponse, ...]


class LogContextResponse(ApiModel):
    schema_version: Literal["1"] = "1"
    resolution: Literal["event", "time", "unscoped"]
    archive: str | None
    line_from: int | None = Field(default=None, ge=0)
    line_to: int | None = Field(default=None, ge=0)
    since: float | None
    until: float | None
    matching_archives: tuple[str, ...]
    message: str | None


class HealthResponse(ApiModel):
    status: Literal["ok", "starting", "ready", "degraded"]
    system_state: HealthState | None = None
