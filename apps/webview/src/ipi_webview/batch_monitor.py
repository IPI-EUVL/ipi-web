from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from ipi_webview.batch import (
    ExperimentHistoryConfig,
    LiveBatchAdapter,
    LiveBatchAdapterConfig,
    LiveBatchSnapshot,
)
from ipi_webview.dds import EcsLiveAdapterConfig
from ipi_webview.dds_monitor import print_updates


def _sources_ready(snapshot: LiveBatchSnapshot) -> bool:
    return snapshot.dds.revision > 0 and snapshot.history.revision > 0


def _change_filter(*, require_ready: bool) -> Callable[[LiveBatchSnapshot], bool]:
    previous_key: Any = object()

    def changed(snapshot: LiveBatchSnapshot) -> bool:
        nonlocal previous_key
        if require_ready and not _sources_ready(snapshot):
            return False

        state = snapshot.dds.experiment.value
        key = (
            snapshot.batch,
            state.phase if state is not None else None,
            snapshot.history.error,
            snapshot.dds.experiment.error,
            snapshot.dds.queue.error,
            snapshot.dds.current_dose.error,
            snapshot.dds.current_time.error,
        )
        if key == previous_key:
            return False
        previous_key = key
        return True

    return changed


def _monitor_value(snapshot: LiveBatchSnapshot) -> dict[str, Any]:
    state = snapshot.dds.experiment.value
    run = state.run if state is not None else None
    return {
        "revision": snapshot.revision,
        "emitted_at": snapshot.emitted_at,
        "live": {
            "experiment_phase": state.phase if state is not None else None,
            "current_run_uuid": run.uuid if run is not None else None,
        },
        "sources": {
            "history_error": snapshot.history.error,
            "experiment_error": snapshot.dds.experiment.error,
            "queue_error": snapshot.dds.queue.error,
            "dose_error": snapshot.dds.current_dose.error,
            "time_error": snapshot.dds.current_time.error,
        },
        "batch": snapshot.batch,
    }


def build_parser() -> argparse.ArgumentParser:
    dds_defaults = EcsLiveAdapterConfig()
    history_defaults = ExperimentHistoryConfig()
    parser = argparse.ArgumentParser(description="Print inferred live exposure batch snapshots until Ctrl+C.")
    parser.add_argument("--host", default=dds_defaults.host, help="DDS server host.")
    parser.add_argument(
        "--data-path",
        default=history_defaults.resolved_data_path,
        help="Directory containing the experiment library.sqlite3 and record folders.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print one compact JSON object per line instead of indented JSON.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print one combined snapshot and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    adapter = LiveBatchAdapter(
        LiveBatchAdapterConfig(
            dds=EcsLiveAdapterConfig(host=args.host),
            history=ExperimentHistoryConfig(data_path=args.data_path),
        )
    )
    return print_updates(
        adapter,
        compact=args.compact,
        max_updates=1 if args.once else None,
        accept_update=_change_filter(require_ready=args.once),
        prepare_update=_monitor_value,
    )


if __name__ == "__main__":
    raise SystemExit(main())
