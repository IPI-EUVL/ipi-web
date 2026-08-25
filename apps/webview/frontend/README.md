# IPI Chamber Webview Frontend

Read-only React and TypeScript interface for live chamber status. The browser uses only same-origin REST and SSE endpoints; it never connects directly to ECS, SQLite, PostgreSQL, Grafana internals, or camera devices.

## Implemented scope

- Live system, experiment, progress, queue, inferred batch, freshness, and issue status
- Accessible 12-position sample stage with established inner/outer geometry
- Sanitized subsystem status view
- Camera configuration placeholder backed by `/api/v1/cameras`
- Indexed exposure browser with waveform and cross-run analysis
- Global ECS log browser with archive/event navigation, buffered directional pages, tail follow, and raw structured records
- External Grafana link

The stack is React, TypeScript, Vite, TanStack Query, Mantine, Lucide, Wouter, Vitest, Testing Library, axe, and Playwright. Wouter provides the small client-only route layer without pulling in React Router's unused server-action surface.

## Runtime data flow

1. Load `GET /api/v1/live` for the first complete screen.
2. Open `new EventSource("/api/v1/live/events")`.
3. Replace the client-side live snapshot whenever a `live` event arrives.
4. Let `EventSource` reconnect automatically. The browser sends `Last-Event-ID`, and the API replays buffered changes or sends the latest snapshot after a restart.
5. Use ordinary REST queries for the exposure and log browsers. Do not send indexed database or journal results through the live SSE stream.

The API already exposes one-based sample numbers and sanitized display models, so React should not import or reproduce ECS protocol logic.

## Suggested source layout

```text
frontend/
  src/
    api/
      client.ts
      live.ts
      types.ts
    app/
      App.tsx
      routes.tsx
    components/
      ExperimentHeader.tsx
      ProgressDisplay.tsx
      SampleStage.tsx
      SystemStatus.tsx
    pages/
      LivePage.tsx
      SubsystemsPage.tsx
      ExperimentsPage.tsx
    test/
  package.json
  vite.config.ts
```

Keep the latest canonical `LiveResponse` in one context/store. Derive presentation details such as “target not reached after user stop” with pure selector functions rather than copying snapshots into many component states.

## Containerized development

Node is not required on the host. Start the standalone API first, then run from the repository root:

```powershell
docker compose -f compose.yaml -f compose.frontend-dev.yaml up -d --wait frontend-dev
```

Open `http://localhost:5173/`. Vite hot reloads bind-mounted source and proxies `/api` and `/health` to `host.docker.internal:8000`. Linux dependencies remain in the `ipi-live_frontend-node-modules` Docker volume.

Run frontend checks in a temporary Node container:

```powershell
$frontend = (Resolve-Path apps/webview/frontend).Path
docker run --rm `
  -v "${frontend}:/workspace" `
  -v ipi-live_frontend-node-modules:/workspace/node_modules `
  -w /workspace node:24-alpine `
  sh -c "npm ci && npm test && npm run lint && npm run typecheck && npm run build"
```

Run desktop/mobile browser checks in the pinned Playwright container:

```powershell
docker compose -f compose.yaml -f compose.frontend-dev.yaml --profile test run --rm frontend-e2e
```

## API contract

The FastAPI OpenAPI schema owns frontend DTOs. Regenerate after public API model or route changes:

```powershell
cd apps/webview
python scripts/export_openapi.py frontend/openapi.json
cd frontend
docker run --rm `
  -v "${PWD}:/workspace" `
  -v ipi-live_frontend-node-modules:/workspace/node_modules `
  -w /workspace node:24-alpine npm run generate:api
```

Commit both `openapi.json` and `src/api/types.generated.ts`.

## Production

The edge Dockerfile uses `node:24-alpine` only as a build stage, runs `npm ci` from the lockfile, and copies `dist/` into nginx. Node is absent from the runtime image and does not need to be installed on deployment hosts.