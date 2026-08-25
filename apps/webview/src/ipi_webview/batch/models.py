from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from ipi_webview.dds.models import DdsLiveSnapshot


@dataclass(frozen=True, slots=True)
class ExperimentHistoryRecord:
    uuid: UUID
    created_at: float
    name: str
    sample_slot: int | None
    target_dose: float | None
    target_time: float | None
    actual_dose: float | None
    actual_time: float | None
    status: str | None
    end_reason: str | None


@dataclass(frozen=True, slots=True)
class ExperimentHistorySnapshot:
    revision: int
    emitted_at: float
    records: tuple[ExperimentHistoryRecord, ...]
    observed_at: float | None
    attempted_at: float | None
    error: str | None
    query_limit: int
    possibly_truncated: bool


class BatchSelectionSource(str, Enum):
    CURRENT_RUN = "current_run"
    QUEUE = "queue"
    HISTORY = "history"
    NONE = "none"


class BatchExposureState(str, Enum):
    QUEUED = "queued"
    CURRENT = "current"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class BatchExposure:
    uuid: UUID | None
    queue_position: int | None
    created_at: float | None
    name: str
    sample_slot: int | None
    target_dose: float | None
    target_time: float | None
    actual_dose: float | None
    actual_time: float | None
    state: BatchExposureState
    status: str | None
    end_reason: str | None


@dataclass(frozen=True, slots=True)
class BatchSlotSummary:
    sample_slot: int
    attempt_count: int
    first_target_dose: float | None
    first_target_time: float | None
    cumulative_actual_dose: float
    cumulative_actual_time: float
    state: BatchExposureState
    abort_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BatchProjection:
    name: str | None
    selection_source: BatchSelectionSource
    exposures: tuple[BatchExposure, ...]
    slots: tuple[BatchSlotSummary, ...]
    unplaced_exposures: tuple[BatchExposure, ...]
    total_queue_count: int
    matching_queue_count: int
    queue_overlap_removed: bool
    history_possibly_truncated: bool


@dataclass(frozen=True, slots=True)
class LiveBatchSnapshot:
    revision: int
    emitted_at: float
    dds: DdsLiveSnapshot
    history: ExperimentHistorySnapshot
    batch: BatchProjection


