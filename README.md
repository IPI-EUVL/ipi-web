# IPI Web

This repository owns the public HTTP edge, chamber live API, web frontend, Grafana, dashboard worker, and PostgreSQL deployment.

## Repository layout

```text
apps/
	webview/
		pyproject.toml       Python project metadata
		src/ipi_webview/     API, batch projection, and DDS adapter package
		tests/               API, batch, and DDS tests by domain
		frontend/            Browser application
	dashboard/
		worker/              Host-run Grafana refresh job
infrastructure/
	nginx/                 Public edge image and routing
compose.yaml             Local edge, Grafana, and PostgreSQL topology
compose.container-api.yaml  Linux/NAS API service overlay
```

`apps/webview` is the Python project root. Its `pyproject.toml`, tests, Dockerfile, and package README stay there; only importable Python modules belong under `src/ipi_webview`. `ipi-chamber-ctl` is an ordinary unpinned requirement: host setup reuses an installed editable source when available and falls back to GitHub otherwise. Published dependencies such as `ipi-ecs` come from PyPI when no editable source is selected.

The dashboard worker is currently a one-shot host-run refresh job and is not started by Compose. Packaging and containerizing it should happen as a separate dashboard-ingestion change; it does not block development of the read-only live frontend.

Run the dashboard refresh job from the repository root with explicit dataset and database settings:

```powershell
$env:EUVL_PATH = "C:\path\to\euvl"
$env:DASHBOARD_DB_URL = "postgresql://ipi-euvl:<password>@127.0.0.1:5432/ipi-data"
python apps/dashboard/worker/dashboard_worker.py
```

## Runtime modes

### Windows workstation

Docker Desktop cannot bind-mount the current Box dataset path because Box exposes it as a Windows volume junction. Run the API directly on Windows and run the other services in Compose.

From `apps/webview`, create the isolated host environment once:

```powershell
.\scripts\setup_host_dev.ps1
```

The setup script detects editable `ipi-ecs`, `ipi-euv-acquisition`, and `ipi-chamber-ctl` sources from the selected Python environment and registers them inside `apps/webview/.venv`. The acquisition source checkout is named `pitaya`. If a source cannot be detected, pass it explicitly:

```powershell
.\scripts\setup_host_dev.ps1 `
	-EcsSource C:\src\ecs `
	-AcquisitionSource C:\src\pitaya `
	-ChamberCtlSource C:\src\chamber-ctl
```

If `chamber-ctl` is not installed editably, it falls back to GitHub; missing published dependencies are resolved from PyPI. The script assumes no workspace-root directory structure and never modifies the selected interpreter.

Set the host-only API configuration and start it:

```powershell
$env:WEBVIEW_ECS_HOST = "<chamber-dds-host>"
$env:WEBVIEW_DATA_PATH = "C:\path\to\Box\datasets"
$env:IPI_ECS_LOG_DIR = "C:\path\to\ecs-logs"
$env:WEBVIEW_DOCS_ENABLED = "true"
$env:WEBVIEW_TRUSTED_HOSTS = "localhost,127.0.0.1,<process-host-IP-or-name>"
.\.venv\Scripts\chamber-webview-api.exe
```

The API listens on `0.0.0.0:8000`, allowing nginx in Docker Desktop to reach it at `host.docker.internal:8000`. Keep that terminal open. In another terminal at the repository root, start the container services:

```powershell
docker compose up -d --build --remove-orphans
```

`--remove-orphans` removes the old `live-api` container now that it is no longer part of the default stack. Until the host API is running, nginx returns `502` for `/api/` and `/health/` requests but continues serving the frontend and Grafana.

### Linux VPS with NAS

When the dataset is available as a normal Linux mount, include the API overlay:

```powershell
docker compose -f compose.yaml -f compose.container-api.yaml up -d --build
```

Set `DATASET_HOST_PATH`, `LOG_HOST_PATH`, `ECS_HOST`, `API_UID`, and `API_GID` in `.env`. The overlay bind-mounts the dataset at `/data`, the ECS journal at `/logs:ro`, and rebuilds nginx to use `live-api:8000` through Compose DNS.

## Environment files

`.env.example` is the committed schema and safe-value template. `.env` is the ignored, machine-specific configuration used by Compose. Copy the example only for initial setup; do not overwrite a working `.env` during updates. The template includes variables for every deployment mode, while a Windows host API deployment needs only the variables consumed by its Compose services.

For the Windows workstation topology, `DATASET_HOST_PATH`, `LOG_HOST_PATH`, `ECS_HOST`, `API_UID`, and `API_GID` are required only by the Linux container-API overlay. `FRONTEND_DEV_PORT` is required only by the frontend development overlay. Their absence from a working Windows `.env` does not affect the default stack.

Docker Compose reads the root `.env` automatically. The standalone `chamber-webview-api` process does not; set its `WEBVIEW_*` variables in the host shell as shown above.

## Edge routing

Containers cannot automatically see arbitrary host files. A file must either be copied into an image at build time or mounted as a volume.

The edge image builds the Vite application in a temporary Node stage and copies the compiled output into nginx. That makes the deployment immutable: the same image contains exactly the tested frontend files, and a VPS does not need Node.js or a manually configured web directory.

In the default workstation topology, nginx reaches:

- `http://host.docker.internal:8000` for the host FastAPI process
- `http://ipi-dashboard:3000` for Grafana

nginx publishes HTTP port 80. Grafana and PostgreSQL are additionally bound to loopback-only ports 3000 and 5432 for local administration and the host-run dashboard worker; neither binding is reachable on external interfaces.

For frontend hot reload without host Node, add the development overlay and open `http://localhost:5173/`:

```powershell
docker compose -f compose.yaml -f compose.frontend-dev.yaml up -d --wait frontend-dev
```

The production frontend remains available through nginx at `http://localhost/`.

### LAN frontend testing

The development overlay binds to loopback by default. To let VPN or LAN peers test the hot-reload frontend, set `FRONTEND_DEV_BIND_ADDRESS=0.0.0.0` in the ignored root `.env`, then recreate only the frontend service:

```powershell
docker compose -f compose.yaml -f compose.frontend-dev.yaml up -d --force-recreate frontend-dev
```

Open `http://<host-LAN-IPv4>:5173/` from a peer; use the numeric address rather than a local hostname unless that hostname is also configured in Vite. The API proxy remains inside the frontend service, so peers do not need direct access to port `8000`. Restore `FRONTEND_DEV_BIND_ADDRESS=127.0.0.1` after testing.

### LAN Grafana testing

Grafana is loopback-only by default. To expose it to VPN or LAN peers, set `GRAFANA_BIND_ADDRESS=0.0.0.0` in `.env`, then set both `GF_SERVER_DOMAIN` and `GF_SERVER_ROOT_URL` to the stable address peers will use, including the port. For example:

```env
GRAFANA_BIND_ADDRESS=0.0.0.0
GF_SERVER_DOMAIN=10.251.166.187
GF_SERVER_ROOT_URL=http://10.251.166.187:3000/
```

Recreate Grafana to apply the changed Compose environment and port mapping:

```powershell
docker compose up -d --force-recreate ipi-dashboard
```

The frontend's Grafana link is compiled from `GF_SERVER_ROOT_URL`; recreate `frontend-dev` as well when using the hot-reload overlay. Restore the loopback binding and `localhost` URL after the test window, or use a stable DNS name before making this persistent.

## Initial configuration

1. Copy `.env.example` to `.env`.
2. Set `POSTGRES_PASSWORD` to the credential currently used by the existing volume. Changing this variable does **not** alter a role already stored in PostgreSQL.
3. Keep `GF_SERVER_DOMAIN=localhost` and `GF_SERVER_ROOT_URL=http://localhost:3000/` while using loopback. Replace them together when a real domain is configured.
4. Configure `DATASET_HOST_PATH`, `LOG_HOST_PATH`, `ECS_HOST`, `API_UID`, and `API_GID` only when using the container-API overlay.

For a NAS, mount the NAS on the VPS first with the operating system, then set `DATASET_HOST_PATH` to that mount. Compose bind-mounts the path into the API container as `/data`; nginx never receives dataset access.

## One-time migration from the dashboard stack

The new stack reuses these existing external volumes:

- `dashboard_ipi-dashboard-persist`
- `dashboard_ipi-dashboard-db-persist`

The Compose-local labels `grafana-data` and `postgres-data` are aliases. Their explicit `name:` settings point to the two existing Docker volume objects above; no replacement `ipi-live_*` volumes are created. The existing Grafana configuration and PostgreSQL data therefore remain in place.

On a new host without the legacy dashboard deployment, create the external volumes once before starting Compose:

```powershell
docker volume create dashboard_ipi-dashboard-persist
docker volume create dashboard_ipi-dashboard-db-persist
```

Use the names configured by `GRAFANA_DATA_VOLUME` and `POSTGRES_DATA_VOLUME` if they differ. Do not create bind mounts for Grafana or PostgreSQL; Docker named volumes are the intended persistent storage.

From the legacy dashboard deployment directory, stop the old containers without deleting volumes:

```powershell
docker compose down
```

Do **not** add `-v` to that command.

Validate and start the workstation stack:

```powershell
docker compose config
docker compose up -d --build --remove-orphans
docker compose ps
```

Updates use the same command. Compose rebuilds changed images and preserves named volumes:

```powershell
git pull
docker compose up -d --build --remove-orphans
```

`docker compose up` reads the current YAML each time and reconciles existing containers. It recreates services whose Compose configuration changed. Use `--build` when Dockerfiles, application source, or build arguments changed. `docker compose restart` only restarts the existing containers and does not apply configuration changes. `docker compose down` removes containers and the project network but preserves named volumes unless volume deletion is explicitly requested.

## Local HTTP checks

With `HTTP_PORT=80`:

```powershell
curl.exe http://localhost/health/live
curl.exe http://localhost/api/v1/live
curl.exe http://localhost:3000/api/health
```

Open the frontend at `http://localhost/` and Grafana directly at `http://localhost:3000/`. The previous failure at port 3000 was caused by the absence of a published host port, not primarily by `GF_SERVER_DOMAIN`. The domain and root URL still need to match the address used by the browser so Grafana generates correct redirects and links.

Inspect logs with:

```powershell
docker compose logs -f edge ipi-dashboard ipi-dashboard-db
```

The standalone API writes its logs to its own PowerShell terminal.

## Release images

The finished system should be distributed as multiple versioned images, not one all-in-one container:

- an edge image containing nginx and the compiled frontend
- an API image containing the Python service for Linux/NAS deployment
- the pinned official Grafana and PostgreSQL images

Publish the custom images to a registry such as GitHub Container Registry and use a release Compose file with `image:` references instead of `build:`. A deployment machine then needs only Docker, the Compose configuration, and its `.env`; it does not need the source repository or Node/Python build toolchains. Keeping services separate preserves independent upgrades, health checks, logs, security boundaries, and persistent-volume ownership.

## VPS networking

The API container uses ordinary outbound networking to reach `ECS_HOST` on TCP port 11750. The university firewall must allow that path from the VPS. If DDS runs on the Docker host itself, set `ECS_HOST=host.docker.internal`; Compose maps that name to the Linux host gateway.

Inbound HTTP port 80 must reach the VPS. PostgreSQL is loopback-only. Grafana 3000, FastAPI 8000, and DDS 11750 should not be opened to the public internet.

## TLS status

This configuration is HTTP-only by explicit choice while certificate ownership is unresolved. Do not treat it as ready for unrestricted public traffic or credentials. Once Tech Services confirms certificate handling, add either mounted university certificates or a Compose-managed ACME client, publish port 443, redirect HTTP to HTTPS, set Grafana's root URL to `https://`, and enable secure cookies.

## Rollback

Images and configuration can be rolled back by checking out the prior revision and running `up -d --build` again. Database and Grafana state remain in the external volumes. Back up those volumes before PostgreSQL or Grafana version upgrades.