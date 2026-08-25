from __future__ import annotations

from ipi_webview.batch.models import (
    BatchProjection,
    BatchSelectionSource,
    ExperimentHistorySnapshot,
    LiveBatchSnapshot,
)
from ipi_webview.batch_monitor import _change_filter, _monitor_value
from ipi_webview.dds.models import DdsLiveSnapshot, ExperimentPhase, ExperimentState, ObservedValue


def _snapshot(revision: int = 1, history_error: str | None = None) -> LiveBatchSnapshot:
    empty = ObservedValue()
    dds = DdsLiveSnapshot(
        revision=revision,
        emitted_at=float(revision),
        transport_ready=ObservedValue(True, 1.0, 1.0, None),
        experiment=ObservedValue(ExperimentState(ExperimentPhase.STOPPED, None), 1.0, 1.0, None),
        experiment_reasons=empty,
        current_dose=empty,
        current_time=empty,
        queue=ObservedValue((), 1.0, 1.0, None),
        stage_position=empty,
        stage_state=empty,
        current_slot=empty,
        subsystems=empty,
    )
    history = ExperimentHistorySnapshot(
        revision=revision,
        emitted_at=float(revision),
        records=(),
        observed_at=1.0,
        attempted_at=1.0,
        error=history_error,
        query_limit=50,
        possibly_truncated=False,
    )
    batch = BatchProjection(None, BatchSelectionSource.NONE, (), (), (), 0, 0, False, False)
    return LiveBatchSnapshot(revision, float(revision), dds, history, batch)


def test_batch_monitor_omits_raw_history_and_subsystems() -> None:
    value = _monitor_value(_snapshot())

    assert set(value) == {"revision", "emitted_at", "live", "sources", "batch"}
    assert "history" not in value
    assert "dds" not in value
    assert value["live"]["experiment_phase"] is ExperimentPhase.STOPPED


def test_batch_monitor_filter_ignores_revision_only_updates_but_reports_errors() -> None:
    changed = _change_filter(require_ready=True)

    assert changed(_snapshot(1)) is True
    assert changed(_snapshot(2)) is False
    assert changed(_snapshot(3, history_error="Dataset unavailable")) is True