from __future__ import annotations

from chamber_ctl.subsystems import uuids
from ipi_webview.api.settings import ApiSettings, CRITICAL_SUBSYSTEM_ALIASES


def test_log_path_uses_the_standard_ecs_variable_with_a_webview_override(monkeypatch) -> None:
    monkeypatch.setenv("IPI_ECS_LOG_DIR", "C:/ecs-logs")
    monkeypatch.delenv("WEBVIEW_LOG_PATH", raising=False)

    assert ApiSettings(_env_file=None).log_path == "C:/ecs-logs"

    monkeypatch.setenv("WEBVIEW_LOG_PATH", "C:/webview-logs")

    assert ApiSettings(_env_file=None).log_path == "C:/webview-logs"


def test_default_critical_subsystems_include_euv_acquisition_not_legacy_oscilloscope() -> None:
    settings = ApiSettings(_env_file=None)

    assert CRITICAL_SUBSYSTEM_ALIASES["euv_acquisition"] == uuids.UUID_EUV_ACQUISITION_CONTROLLER
    assert uuids.UUID_EUV_ACQUISITION_CONTROLLER in settings.critical_subsystem_uuids
    assert uuids.UUID_OSCILLOSCOPE_CONTROLLER not in settings.critical_subsystem_uuids