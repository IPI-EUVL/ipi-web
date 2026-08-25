from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Generic, TypeVar
from uuid import UUID


class ExperimentPhase(IntEnum):
    PREPARING = 0
    INITIALIZING = 1
    RUNNING = 2
    STOPPING = 3
    STOPPED = 4
    CHECKING = 5


class StageState(IntEnum):
    IDLE = 0
    HOMING = 1
    MOVING = 2
    OFFLINE = 3


class StatusSeverity(IntEnum):
    INFO = 0
    WARNING = 1
    ALARM = 2


@dataclass(frozen=True, slots=True)
class ExposureSettingsData:
    name: str
    description: str
    target_time: float | None
    target_dose: float | None
    operator: str
    zr_filter: str
    sample_slot: int | None
    sample_type: str
    base_pressure: float | None
    operating_pressure: float | None
    flow_sccm: float | None


@dataclass(frozen=True, slots=True)
class ExperimentRun:
    uuid: UUID
    experiment_type: str
    name: str
    description: str
    settings: ExposureSettingsData


@dataclass(frozen=True, slots=True)
class ExperimentState:
    phase: ExperimentPhase
    run: ExperimentRun | None


@dataclass(frozen=True, slots=True)
class ExperimentReason:
    subsystem: str
    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class QueueItem:
    position: int
    settings: ExposureSettingsData | None
    error: str | None = None

    def __post_init__(self) -> None:
        if (self.settings is None) == (self.error is None):
            raise ValueError("A queue item must contain either settings or an error.")


@dataclass(frozen=True, slots=True)
class BatchControllerPlanEntry:
    order: int
    sample_slot: int
    mode: str
    target: float
    state: str
    cumulative_dose: float
    cumulative_runtime: float
    attempt_count: int
    remainder: float
    overshoot: float


@dataclass(frozen=True, slots=True)
class BatchControllerAttempt:
    run_uuid: UUID
    sample_slot: int | None
    created_at: float
    end_time: float | None
    status: str | None
    end_reason: str | None
    dose: float | None
    runtime: float | None
    snapshot_count: int
    validation_error: str | None


@dataclass(frozen=True, slots=True)
class BatchControllerState:
    emitted_at: float
    phase: str
    message: str
    last_error: str | None
    lease_owned: bool
    active_batch_uuid: UUID | None
    name: str | None
    description: str | None
    revision: int | None
    manifest_status: str | None
    mode: str | None
    paused: bool | None
    cancel_pending: bool | None
    decision_kind: str | None
    decision_message: str | None
    plan_entries: tuple[BatchControllerPlanEntry, ...]
    attempts: tuple[BatchControllerAttempt, ...]


@dataclass(frozen=True, slots=True)
class SubsystemStatusItem:
    severity: StatusSeverity
    code: int
    message: str


@dataclass(frozen=True, slots=True)
class SubsystemStatus:
    uuid: UUID
    name: str
    connected: bool
    status_items: tuple[SubsystemStatusItem, ...]


ValueT = TypeVar("ValueT")


@dataclass(frozen=True, slots=True)
class ObservedValue(Generic[ValueT]):
    value: ValueT | None = None
    observed_at: float | None = None
    attempted_at: float | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DdsLiveSnapshot:
    revision: int
    emitted_at: float
    transport_ready: ObservedValue[bool]
    experiment: ObservedValue[ExperimentState]
    experiment_reasons: ObservedValue[tuple[ExperimentReason, ...]]
    current_dose: ObservedValue[float]
    current_time: ObservedValue[float]
    queue: ObservedValue[tuple[QueueItem, ...]]
    stage_position: ObservedValue[tuple[float, float]]
    stage_state: ObservedValue[StageState]
    current_slot: ObservedValue[int]
    subsystems: ObservedValue[tuple[SubsystemStatus, ...]]
    batch_controller: ObservedValue[BatchControllerState] = ObservedValue()

