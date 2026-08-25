from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class DataSource(str, Enum):
    TRANSPORT = "transport"
    EXPERIMENT = "experiment"
    EXPERIMENT_REASONS = "experiment_reasons"
    CURRENT_DOSE = "current_dose"
    CURRENT_TIME = "current_time"
    QUEUE = "queue"
    BATCH_CONTROLLER = "batch_controller"
    STAGE_POSITION = "stage_position"
    STAGE_STATE = "stage_state"
    CURRENT_SLOT = "current_slot"
    SUBSYSTEMS = "subsystems"


@dataclass(frozen=True, slots=True)
class TransportEvent:
    source: DataSource
    received_at: float
    sampled_at: float
    value: Any = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.error is not None and self.value is not None:
            raise ValueError("A failed transport event cannot contain a value.")
