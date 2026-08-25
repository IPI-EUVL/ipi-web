from __future__ import annotations

import argparse
import json
import queue
import sys
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, Callable, Protocol, TextIO
from uuid import UUID

from ipi_webview.dds import EcsLiveAdapter, EcsLiveAdapterConfig


class SnapshotSource(Protocol):
    def start(self) -> None: ...

    def get_update(self, timeout: float | None = None) -> Any: ...

    def close(self) -> None: ...


def to_json_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: to_json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): to_json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [to_json_value(item) for item in value]
    return value


def print_updates(
    adapter: SnapshotSource,
    *,
    output: TextIO = sys.stdout,
    compact: bool = False,
    max_updates: int | None = None,
    accept_update: Callable[[Any], bool] | None = None,
    prepare_update: Callable[[Any], Any] | None = None,
) -> int:
    update_count = 0
    adapter.start()
    try:
        while max_updates is None or update_count < max_updates:
            try:
                snapshot = adapter.get_update(timeout=1.0)
            except queue.Empty:
                continue

            if accept_update is not None and not accept_update(snapshot):
                continue

            printable = prepare_update(snapshot) if prepare_update is not None else snapshot

            print(
                json.dumps(
                    to_json_value(printable),
                    indent=None if compact else 2,
                    separators=(",", ":") if compact else None,
                ),
                file=output,
                flush=True,
            )
            update_count += 1
    except KeyboardInterrupt:
        return 0
    finally:
        adapter.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    defaults = EcsLiveAdapterConfig()
    parser = argparse.ArgumentParser(description="Print read-only chamber DDS adapter snapshots until Ctrl+C.")
    parser.add_argument("--host", default=defaults.host, help="DDS server host.")
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print one compact JSON object per line instead of indented JSON.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print one snapshot and exit. The first snapshot may not contain live values yet.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    adapter = EcsLiveAdapter(EcsLiveAdapterConfig(host=args.host))
    return print_updates(adapter, compact=args.compact, max_updates=1 if args.once else None)


if __name__ == "__main__":
    raise SystemExit(main())
