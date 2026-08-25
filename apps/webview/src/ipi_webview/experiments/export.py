from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import zipfile
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ipi_webview.experiments.models import ExperimentDetail


class ExperimentExportError(RuntimeError):
    """A safe experiment archive could not be produced."""


class ExperimentExportTooLarge(ExperimentExportError):
    """An experiment archive exceeds its configured input budget."""


@dataclass(frozen=True, slots=True)
class ExperimentExportArchive:
    path: Path
    filename: str
    size_bytes: int


def build_experiment_zip(
    source_folder: Path,
    detail: ExperimentDetail,
    *,
    max_input_bytes: int,
    retry_attempts: int,
    retry_delay: float,
) -> ExperimentExportArchive:
    if max_input_bytes < 1:
        raise ValueError("Exposure export byte limit must be positive.")
    if retry_attempts < 1 or retry_delay < 0:
        raise ValueError("Exposure export retry settings are invalid.")
    expected_bytes = sum(resource.size_bytes or 0 for resource in detail.resources)
    if expected_bytes > max_input_bytes:
        raise ExperimentExportTooLarge(
            f"Exposure export input is {expected_bytes} bytes; the limit is {max_input_bytes}."
        )

    run_id = str(detail.summary.run_id)
    errors: list[str] = []
    manifest = {
        "schema_version": "1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "run": asdict(detail.summary),
        "resources": [asdict(resource) for resource in detail.resources],
        "exported_resources": [],
        "errors": errors,
    }
    file_descriptor, temp_name = tempfile.mkstemp(prefix=f"experiment-{run_id}-", suffix=".zip")
    os.close(file_descriptor)
    archive_path = Path(temp_name)
    copied_bytes = 0
    try:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for resource in detail.resources:
                source = source_folder / resource.name
                staged_path, staged_size, error = _stage_resource(
                    source,
                    retry_attempts=retry_attempts,
                    retry_delay=retry_delay,
                )
                if error is not None or staged_path is None:
                    errors.append(error or f"Registered resource {resource.name!r} could not be staged.")
                    continue
                try:
                    if copied_bytes + staged_size > max_input_bytes:
                        raise ExperimentExportTooLarge(
                            f"Exposure export input exceeds the {max_input_bytes}-byte limit."
                        )
                    archive.write(staged_path, f"{run_id}/resources/{resource.name}")
                    copied_bytes += staged_size
                    manifest["exported_resources"].append(resource.name)
                finally:
                    staged_path.unlink(missing_ok=True)
            archive.writestr(f"{run_id}/manifest.json", json.dumps(manifest, indent=2, default=str))
            archive.writestr(f"{run_id}/export-errors.json", json.dumps(manifest["errors"], indent=2))
        return ExperimentExportArchive(
            path=archive_path,
            filename=f"experiment-{run_id}.zip",
            size_bytes=archive_path.stat().st_size,
        )
    except (OSError, zipfile.BadZipFile) as exc:
        archive_path.unlink(missing_ok=True)
        raise ExperimentExportError("Exposure archive could not be created.") from exc
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise


def _stage_resource(
    source: Path,
    *,
    retry_attempts: int,
    retry_delay: float,
) -> tuple[Path | None, int, str | None]:
    last_error: OSError | None = None
    for attempt in range(1, retry_attempts + 1):
        file_descriptor, temp_name = tempfile.mkstemp(prefix="experiment-resource-", suffix=".tmp")
        os.close(file_descriptor)
        staged_path = Path(temp_name)
        try:
            with source.open("rb") as source_file, staged_path.open("wb") as target_file:
                shutil.copyfileobj(source_file, target_file, length=1024 * 1024)
            return staged_path, staged_path.stat().st_size, None
        except OSError as exc:
            last_error = exc
            staged_path.unlink(missing_ok=True)
            if attempt < retry_attempts and retry_delay:
                time.sleep(retry_delay)
    return (
        None,
        0,
        f"Registered resource {source.name!r} is unavailable after {retry_attempts} export attempts ({type(last_error).__name__}).",
    )