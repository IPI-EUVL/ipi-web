# IPI Chamber Webview

Read-only live adapter and HTTP API for the IPI EUV experiment chamber.

## Local API

Create an isolated host environment. The script reuses any editable `ipi-ecs` and `ipi-chamber-ctl` sources already registered in the selected Python environment:

```powershell
.\scripts\setup_host_dev.ps1
$env:WEBVIEW_ECS_HOST = "<chamber-dds-host>"
$env:WEBVIEW_DATA_PATH = "C:\path\to\Box\datasets"
$env:IPI_ECS_LOG_DIR = "C:\path\to\ecs-logs"
.\.venv\Scripts\chamber-webview-api.exe
```

`ipi-chamber-ctl` is an ordinary unpinned project requirement, so an installed local editable copy satisfies it. If the selected Python has no editable `chamber-ctl`, the setup script installs the GitHub repository as a fallback. Missing `ipi-ecs` is resolved from PyPI. No workspace-root layout is assumed.

You can override detection explicitly when needed:

```powershell
.\scripts\setup_host_dev.ps1 -EcsSource C:\src\ecs -ChamberCtlSource C:\src\chamber-ctl
```

Do not run setup in a shared interpreter; `.venv` keeps dependency changes isolated.

The executable does not load the repository's Compose `.env` file. Set the host process's `WEBVIEW_*` variables in the shell before starting it.

The default endpoints are:

- `http://127.0.0.1:8000/api/v1/live`
- `http://127.0.0.1:8000/api/v1/live/events`
- `http://127.0.0.1:8000/api/v1/subsystems`
- `http://127.0.0.1:8000/api/v1/cameras`
- `http://127.0.0.1:8000/api/v1/experiments`
- `http://127.0.0.1:8000/api/v1/experiments/options`
- `http://127.0.0.1:8000/api/v1/experiments/{run_id}`
- `http://127.0.0.1:8000/api/v1/experiments/{run_id}/events`
- `http://127.0.0.1:8000/api/v1/experiments/{run_id}/export`
- `http://127.0.0.1:8000/api/v1/logs/archives`
- `http://127.0.0.1:8000/api/v1/logs/entries`
- `http://127.0.0.1:8000/api/v1/logs/events`
- `http://127.0.0.1:8000/api/v1/logs/context`
- `http://127.0.0.1:8000/health/live`
- `http://127.0.0.1:8000/health/ready`
- `http://127.0.0.1:8000/docs` when `WEBVIEW_DOCS_ENABLED=true`

Useful environment variables:

```text
WEBVIEW_ECS_HOST=127.0.0.1
WEBVIEW_DATA_PATH=C:/path/to/datasets
IPI_ECS_LOG_DIR=C:/path/to/ecs-logs
WEBVIEW_EXPERIMENT_RESOURCE_RETRY_ATTEMPTS=3
WEBVIEW_EXPERIMENT_RESOURCE_RETRY_DELAY=0.25
WEBVIEW_EXPERIMENT_SNAPSHOT_ANALYSIS_WORKERS=12
WEBVIEW_EXPERIMENT_WAVEFORM_MAX_POINTS=2000000
WEBVIEW_EXPERIMENT_EXPORT_MAX_INPUT_BYTES=21474836480
WEBVIEW_EXPERIMENT_WAVEFORM_MAX_POINTS=2000000
WEBVIEW_EXPERIMENT_EXPORT_MAX_INPUT_BYTES=21474836480
WEBVIEW_CRITICAL_SUBSYSTEMS=exposure,queue,oscilloscope,sample_motion,target,laser
WEBVIEW_LIVE_STALE_AFTER=10
WEBVIEW_HISTORY_STALE_AFTER=15
WEBVIEW_SSE_HEARTBEAT_INTERVAL=15
WEBVIEW_DOCS_ENABLED=true
WEBVIEW_TRUSTED_HOSTS=localhost,127.0.0.1
```

The API uses the standard `IPI_ECS_LOG_DIR` when it is set. `WEBVIEW_LOG_PATH` is an optional explicit override for a separately mounted browser path. When neither is set, the API remains available and log-browser endpoints return `503` with a configuration message. The path must point to an ECS log root that contains `current/` and optionally `archives/`; the browser opens every index read-only, keeps at most five 100-row pages in memory, and reads full structured records only on demand.

Exposure registry entries are returned even when individual Box-backed files cannot be hydrated. Resource opens and snapshot analysis use the bounded retry settings above; exhausted optional resources are reported as unavailable while other run data remains readable.

Waveform NPZ files store pulse-local time columns that reset at each pulse. The API reconstructs a monotonic snapshot timeline from the registered pulse timestamps while preserving every stored voltage point. Browser charts use the full snapshot extrema as a fixed y range and format elapsed x values in seconds, milliseconds, microseconds, or nanoseconds based on the visible span.

A background coordinator calculates and caches snapshot dose analysis by waveform/metadata file signature. It reuses a bounded pool of 1-20 snapshot workers (12 by default), so Box-backed snapshot files hydrate concurrently. Run dose-series requests return `202` while uncached snapshots are processing, then return cumulative dose and dose-rate points with per-snapshot errors. The same cache serves Overview, waveform-derived pulse graphs, and cross-run comparison. Available graph views are:

Raw waveform pulse measurements are authoritative for dose and are accumulated regardless of laser/chopper transmitting state, so unexpected physical exposures remain visible. Negative calibrated pulse values are treated as noise and cannot subtract prior dose. The timing state controls transmitting-runtime coordinates and annotations only; capture-timeline dose totals are retained for audit and never replace waveform-derived dose.

- Full voltage versus reconstructed elapsed time for one snapshot.
- Peak voltage versus pulse time with rolling windows 1/10/50/100.
- Dose per pulse versus pulse index with rolling windows 1/10/50/100.
- Per-run cumulative dose or dose rate versus elapsed time.
- Multi-run cumulative dose or dose-rate overlays with CSV download.

New exposure records additionally carry a durable run-event journal. The Events tab and `/api/v1/experiments/{run_id}/events` expose its raw lifecycle and timing records, including stream-integrity warnings. A missing journal on an older record is a valid empty timeline; this release does not backfill historical records from logs or snapshots.

Single-run graph responses use schema version `2` and include annotation points/intervals. Lifecycle phases are retained as boundaries; laser trigger eligibility and EUV-transmitting state render as intervals. The run timeline offers transmitting-runtime and PREINIT-relative wall-time modes. Native snapshot wall-time annotations use producer timestamps; compressed apparent-time and pulse-index views snap timing transitions to the first following pulse and identify that projection in the annotation data.

Single-run ZIP exports include all resources that can be hydrated plus a manifest and explicit errors for unavailable registered resources. Export and full-waveform requests enforce the configured byte/point limits.

The experiment browser exposes indexed operator/Zr facets, date and numeric ranges, single-run partial ZIP exports, and lazy waveform graphs. Graphs use uPlot: drag selects a zoom range, the mouse wheel zooms around the cursor, Shift-drag or middle-drag pans, and Reset restores the full x-range. The chart component also supports efficient `setData` updates and a follow-latest window for future live traces.

The API process must use exactly one Uvicorn worker. The in-memory DDS adapter and SSE event buffer are process-local.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

See [frontend/README.md](frontend/README.md) for the recommended client architecture and [../../README.md](../../README.md) for container deployment.