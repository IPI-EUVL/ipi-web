from __future__ import annotations

import argparse
import json
from pathlib import Path

from ipi_webview.api.main import app


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the public webview OpenAPI contract.")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()