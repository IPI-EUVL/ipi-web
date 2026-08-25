from __future__ import annotations

import os
from uuid import UUID

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from chamber_ctl import ECS_IP
from chamber_ctl.subsystems import uuids
from ipi_ecs.logging.viewer import ENV_LOG_DIR_DEFAULT
from ipi_webview.batch.history import default_data_path


CRITICAL_SUBSYSTEM_ALIASES: dict[str, UUID] = {
    "exposure": uuids.UUID_EXPOSURE_CONTROLLER,
    "queue": uuids.UUID_EXPERIMENT_QUEUE_CONTROLLER,
    "euv_acquisition": uuids.UUID_EUV_ACQUISITION_CONTROLLER,
    "sample_motion": uuids.UUID_SAMPLE_MOTION_CONTROLLER,
    "target": uuids.UUID_TARGET_CONTROLLER,
    "laser": uuids.UUID_LASER_CONTROLLER,
    "development_metrics": uuids.UUID_DEVELOPMENT_METRICS_CONTROLLER,
    "lifecycle": uuids.UUID_LIFECYCLE_MANAGER,
}

SUBSYSTEM_LABELS: dict[UUID, str] = {
    uuids.UUID_EXPOSURE_CONTROLLER: "Exposure Controller",
    uuids.UUID_EXPERIMENT_QUEUE_CONTROLLER: "Exposure Queue Controller",
    uuids.UUID_EUV_ACQUISITION_CONTROLLER: "EUV Acquisition Controller",
    uuids.UUID_SAMPLE_MOTION_CONTROLLER: "Sample Motion Controller",
    uuids.UUID_TARGET_CONTROLLER: "Target Controller",
    uuids.UUID_LASER_CONTROLLER: "Laser Controller",
    uuids.UUID_DEVELOPMENT_METRICS_CONTROLLER: "Development Metrics Controller",
    uuids.UUID_LIFECYCLE_MANAGER: "Lifecycle Manager",
}


def _default_log_path() -> str | None:
    value = os.getenv(ENV_LOG_DIR_DEFAULT)
    return value.strip() if value and value.strip() else None


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WEBVIEW_", case_sensitive=False, extra="ignore")

    ecs_host: str = ECS_IP
    data_path: str = Field(default_factory=default_data_path)
    log_path: str | None = Field(default_factory=_default_log_path)
    experiment_type: str = "exposure"
    experiment_resource_retry_attempts: int = Field(default=3, ge=1, le=10)
    experiment_resource_retry_delay: float = Field(default=0.25, ge=0, le=10)
    experiment_snapshot_analysis_workers: int = Field(default=12, ge=1, le=20)
    experiment_waveform_max_points: int = Field(default=2_000_000, ge=1)
    experiment_export_max_input_bytes: int = Field(default=20 * 1024 * 1024 * 1024, ge=1)
    critical_subsystems: str = "exposure,queue,euv_acquisition,sample_motion,target,laser"
    live_stale_after: float = Field(default=10.0, gt=0)
    history_stale_after: float = Field(default=15.0, gt=0)
    sse_heartbeat_interval: float = Field(default=15.0, gt=0)
    sse_event_buffer_size: int = Field(default=100, ge=1)
    docs_enabled: bool = True
    trusted_hosts: str = "localhost,127.0.0.1,live.ipi.illinois.edu"

    @property
    def critical_subsystem_uuids(self) -> frozenset[UUID]:
        resolved = set()
        for raw_token in self.critical_subsystems.split(","):
            token = raw_token.strip().lower()
            if not token:
                continue
            subsystem_uuid = CRITICAL_SUBSYSTEM_ALIASES.get(token)
            if subsystem_uuid is None:
                try:
                    subsystem_uuid = UUID(token)
                except ValueError as exc:
                    choices = ", ".join(sorted(CRITICAL_SUBSYSTEM_ALIASES))
                    raise ValueError(f"Unknown critical subsystem '{raw_token.strip()}'. Expected one of: {choices}.") from exc
            resolved.add(subsystem_uuid)
        return frozenset(resolved)

    @property
    def trusted_host_list(self) -> list[str]:
        return [host.strip() for host in self.trusted_hosts.split(",") if host.strip()]
