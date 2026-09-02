from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated, Literal
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask

from ipi_webview.api.mapper import PublicSnapshotMapper
from ipi_webview.api.models import (
    CamerasResponse,
    ExperimentDataIssueResponse,
    ExperimentDetailResponse,
    ExposureEventTimelineResponse,
    ExperimentFilterOptionsResponse,
    ExperimentFiltersResponse,
    ExperimentListItemResponse,
    ExperimentMetricsResponse,
    ExperimentPageResponse,
    ExperimentResourcesResponse,
    HealthResponse,
    LogRangeResponse,
    LogArchiveResponse,
    LogArchivesResponse,
    LogContextResponse,
    LogEntryResponse,
    LogEventResponse,
    LogEventsResponse,
    LogFiltersResponse,
    LogPageResponse,
    LiveResponse,
    ObserverDoseComparisonResponse,
    RegisteredResourceResponse,
    RunDoseSeriesResponse,
    SnapshotResponse,
    SnapshotAnalysisResponse,
    SnapshotGraphSeriesResponse,
    SubsystemsResponse,
)
from ipi_webview.api.service import LiveApiService, SnapshotSource
from ipi_webview.api.settings import ApiSettings
from ipi_webview.api.store import SnapshotStore
from ipi_webview.batch import ExperimentHistoryConfig, LiveBatchAdapter, LiveBatchAdapterConfig
from ipi_webview.dds import EcsLiveAdapterConfig
from ipi_webview.experiments import (
    ExperimentBrowserConfig,
    ExperimentBrowserRepository,
    ExperimentExportError,
    ExperimentExportTooLarge,
    ExperimentFilters,
    ExperimentIntegrityError,
    ExperimentNotFoundError,
    ExperimentResourceUnavailable,
    ExperimentResponseTooLarge,
    ExperimentRepositoryUnavailable,
)
from ipi_webview.experiments.models import ExperimentDetail, ExperimentListItem, RegisteredResource
from ipi_webview.logs import (
    LogBrowserNotFoundError,
    LogBrowserRepository,
    LogBrowserUnavailable,
    LogFilters,
)


async def _require_latest(store: SnapshotStore) -> LiveResponse:
    snapshot = await store.latest()
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Live data is starting.")
    return snapshot


def _parse_last_event_id(raw_value: str | None) -> int | None:
    if raw_value is None or not raw_value.strip():
        return None
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer.") from exc
    if value < 0:
        raise HTTPException(status_code=400, detail="Last-Event-ID cannot be negative.")
    return value


async def sse_stream(
    request: Request,
    store: SnapshotStore,
    *,
    after_event_id: int | None,
    heartbeat_interval: float,
) -> AsyncIterator[str]:
    cursor = after_event_id
    while not await request.is_disconnected():
        events = await store.wait_for_events(cursor, heartbeat_interval)
        if not events:
            yield ": heartbeat\n\n"
            continue
        for event in events:
            cursor = event.id
            yield event.to_sse()


def _default_source(settings: ApiSettings) -> SnapshotSource:
    return LiveBatchAdapter(
        LiveBatchAdapterConfig(
            dds=EcsLiveAdapterConfig(host=settings.ecs_host),
            history=ExperimentHistoryConfig(data_path=settings.data_path),
        )
    )


def _resource_response(resource: RegisteredResource) -> RegisteredResourceResponse:
    return RegisteredResourceResponse(
        name=resource.name,
        resource_type=resource.resource_type,
        size_bytes=resource.size_bytes,
        available=resource.available,
        downloadable=resource.downloadable,
        error=resource.error,
    )


def _list_item_response(item: ExperimentListItem) -> ExperimentListItemResponse:
    return ExperimentListItemResponse(
        run_id=item.run_id,
        created_at=item.created_at,
        name=item.name,
        description=item.description,
        sample=item.sample,
        operator=item.operator,
        zr_filter=item.zr_filter,
        target_dose=item.target_dose,
        target_time=item.target_time,
        actual_dose=item.actual_dose,
        runtime=item.runtime,
        effective_dose_rate=item.effective_dose_rate,
        exposed_thickness_nm=item.exposed_thickness_nm,
        blank_thickness_nm=item.blank_thickness_nm,
        percent_development=item.percent_development,
        status=item.status,
        end_reason=item.end_reason,
    )


def _experiment_detail_response(detail: ExperimentDetail) -> ExperimentDetailResponse:
    return ExperimentDetailResponse(
        summary=_list_item_response(detail.summary),
        settings=detail.settings,
        metadata=detail.metadata,
        end_metadata=detail.end_metadata,
        tags=detail.tags,
        resources=tuple(_resource_response(resource) for resource in detail.resources),
        snapshots=tuple(
            SnapshotResponse(
                snapshot_id=snapshot.snapshot_id,
                format=snapshot.snapshot_format,
                waveform=_resource_response(snapshot.waveform),
                metadata=None if snapshot.metadata is None else _resource_response(snapshot.metadata),
                final_sequence=snapshot.final_sequence,
            )
            for snapshot in detail.snapshots
        ),
        metrics=ExperimentMetricsResponse(
            measurements=tuple(
                {
                    "spot_type": measurement.spot_type,
                    "thickness_nm": measurement.thickness_nm,
                    "goodness_of_fit": measurement.goodness_of_fit,
                }
                for measurement in detail.metrics.measurements
            ),
            exposed_average_nm=detail.metrics.exposed_average_nm,
            blank_average_nm=detail.metrics.blank_average_nm,
            percent_development=detail.metrics.percent_development,
            degraded=detail.metrics.degraded,
            error=detail.metrics.error,
        ),
        log_range=LogRangeResponse(
            event_id=detail.log_range.event_id,
            created_at=detail.log_range.created_at,
            ended_at=detail.log_range.ended_at,
            complete=detail.log_range.complete,
        ),
        issues=tuple(
            ExperimentDataIssueResponse(
                section=issue.section,
                resource_name=issue.resource_name,
                kind=issue.kind,
                message=issue.message,
            )
            for issue in detail.issues
        ),
    )


def _experiment_error_to_http(exc: Exception) -> HTTPException:
    if isinstance(exc, ExperimentNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exposure run was not found.")
    if isinstance(exc, ExperimentIntegrityError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, ExperimentRepositoryUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Exposure index is unavailable.")
    if isinstance(exc, ExperimentResourceUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, ExperimentResponseTooLarge):
        return HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc))
    if isinstance(exc, ExperimentExportTooLarge):
        return HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc))
    if isinstance(exc, ExperimentExportError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    raise exc


def _log_error_to_http(exc: Exception) -> HTTPException:
    if isinstance(exc, LogBrowserNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log archive was not found.")
    if isinstance(exc, LogBrowserUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Log browser is unavailable.")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    raise exc


def _log_filters_response(filters: LogFilters) -> LogFiltersResponse:
    return LogFiltersResponse(**asdict(filters))


def _parse_resource_range(raw_value: str | None, size_bytes: int) -> tuple[int, int] | None:
    if raw_value is None:
        return None
    if not raw_value.startswith("bytes=") or "," in raw_value:
        raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, detail="Invalid Range header.")
    start_text, separator, end_text = raw_value[6:].strip().partition("-")
    if not separator or (not start_text and not end_text):
        raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, detail="Invalid Range header.")
    try:
        if start_text:
            start = int(start_text)
            end = size_bytes - 1 if not end_text else int(end_text)
        else:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                raise ValueError
            start = max(size_bytes - suffix_length, 0)
            end = size_bytes - 1
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, detail="Invalid Range header.") from exc
    if start < 0 or end < start or start >= size_bytes:
        raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, detail="Range is outside the resource.")
    return start, min(end, size_bytes - 1)


def _stream_open_resource(open_resource, start: int, length: int):
    try:
        open_resource.file.seek(start)
        remaining = length
        while remaining:
            chunk = open_resource.file.read(min(64 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        open_resource.close()


def create_app(
    settings: ApiSettings | None = None,
    *,
    source: SnapshotSource | None = None,
    experiment_repository: ExperimentBrowserRepository | None = None,
    log_repository: LogBrowserRepository | None = None,
) -> FastAPI:
    settings = settings or ApiSettings()
    store = SnapshotStore(settings.sse_event_buffer_size)
    mapper = PublicSnapshotMapper(
        settings.critical_subsystem_uuids,
        live_stale_after=settings.live_stale_after,
        history_stale_after=settings.history_stale_after,
    )
    source = source or _default_source(settings)
    service = LiveApiService(source, mapper, store)
    experiment_repository = experiment_repository or ExperimentBrowserRepository(
        ExperimentBrowserConfig(
            settings.data_path,
            experiment_type=settings.experiment_type,
            resource_retry_attempts=settings.experiment_resource_retry_attempts,
            resource_retry_delay=settings.experiment_resource_retry_delay,
            snapshot_analysis_workers=settings.experiment_snapshot_analysis_workers,
            waveform_max_points=settings.experiment_waveform_max_points,
            export_max_input_bytes=settings.experiment_export_max_input_bytes,
        )
    )
    if log_repository is None and settings.log_path and settings.log_path.strip():
        log_repository = LogBrowserRepository(settings.log_path.strip())

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        experiment_repository.start()
        if log_repository is not None:
            log_repository.start()
        await service.start()
        try:
            yield
        finally:
            await service.stop()
            if log_repository is not None:
                log_repository.close()
            experiment_repository.close()

    app = FastAPI(
        title="IPI Chamber Live API",
        version="1.0.0",
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
    )
    if settings.trusted_host_list:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)

    app.state.settings = settings
    app.state.store = store
    app.state.service = service
    app.state.experiment_repository = experiment_repository
    app.state.log_repository = log_repository

    @app.get("/api/v1/live", response_model=LiveResponse)
    async def get_live() -> LiveResponse:
        return await _require_latest(store)

    @app.get("/api/v1/subsystems", response_model=SubsystemsResponse)
    async def get_subsystems() -> SubsystemsResponse:
        snapshot = await _require_latest(store)
        return SubsystemsResponse(
            revision=snapshot.revision,
            generated_at=snapshot.generated_at,
            system=snapshot.system,
            items=snapshot.subsystems,
        )

    @app.get("/api/v1/cameras", response_model=CamerasResponse)
    async def get_cameras() -> CamerasResponse:
        return CamerasResponse()

    @app.get("/api/v1/experiments", response_model=ExperimentPageResponse)
    def get_experiments(
        page: int = Query(default=1, ge=1),
        page_size: int | None = Query(default=None),
        name: str | None = None,
        created_min: float | None = None,
        created_max: float | None = None,
        min_actual_dose: float | None = None,
        max_actual_dose: float | None = None,
        min_target_dose: float | None = None,
        max_target_dose: float | None = None,
        min_runtime: float | None = None,
        max_runtime: float | None = None,
        zr_filter: str | None = None,
        sample: str | None = None,
        operator: str | None = None,
    ) -> ExperimentPageResponse:
        try:
            filters = ExperimentFilters(
                name=name,
                created_min=created_min,
                created_max=created_max,
                min_actual_dose=min_actual_dose,
                max_actual_dose=max_actual_dose,
                min_target_dose=min_target_dose,
                max_target_dose=max_target_dose,
                min_runtime=min_runtime,
                max_runtime=max_runtime,
                zr_filter=zr_filter,
                sample=sample,
                operator=operator,
            )
            result = experiment_repository.list_page(filters, page=page, page_size=page_size)
        except Exception as exc:
            raise _experiment_error_to_http(exc) from exc
        return ExperimentPageResponse(
            page=result.page,
            page_size=result.page_size,
            total_count=result.total_count,
            total_pages=result.total_pages,
            filters=ExperimentFiltersResponse(**asdict(result.filters)),
            items=tuple(_list_item_response(item) for item in result.items),
        )

    @app.get("/api/v1/experiments/options", response_model=ExperimentFilterOptionsResponse)
    def get_experiment_filter_options() -> ExperimentFilterOptionsResponse:
        try:
            options = experiment_repository.get_filter_options()
        except Exception as exc:
            raise _experiment_error_to_http(exc) from exc
        return ExperimentFilterOptionsResponse(**asdict(options))

    @app.get("/api/v1/experiments/{run_id}", response_model=ExperimentDetailResponse)
    def get_experiment(run_id: UUID) -> ExperimentDetailResponse:
        try:
            detail = experiment_repository.get_detail(run_id)
        except Exception as exc:
            raise _experiment_error_to_http(exc) from exc
        return _experiment_detail_response(detail)

    @app.get("/api/v1/experiments/{run_id}/resources", response_model=ExperimentResourcesResponse)
    def get_experiment_resources(run_id: UUID) -> ExperimentResourcesResponse:
        try:
            detail = experiment_repository.get_detail(run_id)
        except Exception as exc:
            raise _experiment_error_to_http(exc) from exc
        return ExperimentResourcesResponse(
            run_id=run_id,
            items=tuple(_resource_response(resource) for resource in detail.resources),
        )

    @app.get("/api/v1/experiments/{run_id}/export", response_class=FileResponse)
    def export_experiment(run_id: UUID) -> FileResponse:
        try:
            archive = experiment_repository.create_export(run_id)
        except Exception as exc:
            raise _experiment_error_to_http(exc) from exc
        return FileResponse(
            archive.path,
            filename=archive.filename,
            media_type="application/zip",
            background=BackgroundTask(archive.path.unlink, missing_ok=True),
        )

    @app.get("/api/v1/experiments/{run_id}/metrics", response_model=ExperimentMetricsResponse)
    def get_experiment_metrics(run_id: UUID) -> ExperimentMetricsResponse:
        try:
            metrics = experiment_repository.get_metrics(run_id)
        except Exception as exc:
            raise _experiment_error_to_http(exc) from exc
        return ExperimentMetricsResponse(
            measurements=tuple(
                {
                    "spot_type": measurement.spot_type,
                    "thickness_nm": measurement.thickness_nm,
                    "goodness_of_fit": measurement.goodness_of_fit,
                }
                for measurement in metrics.measurements
            ),
            exposed_average_nm=metrics.exposed_average_nm,
            blank_average_nm=metrics.blank_average_nm,
            percent_development=metrics.percent_development,
            degraded=metrics.degraded,
            error=metrics.error,
        )

    @app.get("/api/v1/experiments/{run_id}/events", response_model=ExposureEventTimelineResponse)
    def get_exposure_events(run_id: UUID) -> ExposureEventTimelineResponse:
        try:
            timeline = experiment_repository.get_event_timeline(run_id)
        except Exception as exc:
            raise _experiment_error_to_http(exc) from exc
        return ExposureEventTimelineResponse(
            run_id=timeline.run_id,
            events=tuple(
                {
                    "event_id": event.event_id,
                    "stream_id": event.stream_id,
                    "stream_name": event.stream_name,
                    "sequence": event.sequence,
                    "kind": event.kind,
                    "producer_unix_ns": event.producer_unix_ns,
                    "producer_monotonic_ns": event.producer_monotonic_ns,
                    "ingest_unix_ns": event.ingest_unix_ns,
                    "payload": event.payload,
                    "capture_session_id": event.capture_session_id,
                    "next_sequence": event.next_sequence,
                    "runtime_seconds": event.runtime_seconds,
                }
                for event in timeline.events
            ),
            complete=timeline.complete,
            issues=timeline.issues,
            wall_time_origin_unix_ns=timeline.wall_time_origin_unix_ns,
        )

    @app.get("/api/v1/experiments/{run_id}/dose-series", response_model=RunDoseSeriesResponse)
    def get_run_dose_series(
        run_id: UUID,
        time_mode: str = Query(default="runtime", pattern="^(runtime|wall)$"),
        resolution: str = Query(default="full", pattern="^(full|thumbnail)$"),
    ) -> RunDoseSeriesResponse:
        try:
            series = experiment_repository.get_run_dose_series(
                run_id,
                time_mode=time_mode,
                resolution=resolution,
            )
        except Exception as exc:
            raise _experiment_error_to_http(exc) from exc
        return _run_dose_series_response(series)

    @app.get(
        "/api/v1/experiments/{run_id}/observer-dose-series",
        response_model=ObserverDoseComparisonResponse,
    )
    def get_observer_dose_series(
        run_id: UUID,
        resolution: str = Query(default="full", pattern="^(full|thumbnail)$"),
    ) -> ObserverDoseComparisonResponse:
        try:
            comparison = experiment_repository.get_observer_dose_comparison(
                run_id,
                resolution=resolution,
            )
        except Exception as exc:
            raise _experiment_error_to_http(exc) from exc
        return ObserverDoseComparisonResponse(
            run_id=comparison.run_id,
            status=comparison.status,
            series=tuple(
                {
                    "session_id": series.session_id,
                    "source_kind": series.source_kind,
                    "source_id": series.source_id,
                    "algorithm": series.algorithm,
                    "algorithm_version": series.algorithm_version,
                    "status": series.status,
                    "points": tuple(
                        {
                            "wall_elapsed_seconds": point.wall_elapsed_seconds,
                            "dose_increment_mj_cm2": point.dose_increment_mj_cm2,
                            "cumulative_dose_mj_cm2": point.cumulative_dose_mj_cm2,
                            "source_sequence": point.source_sequence,
                            "represented_pulse_count": point.represented_pulse_count,
                        }
                        for point in series.points
                    ),
                    "raw_point_count": series.raw_point_count,
                    "pulse_count": series.pulse_count,
                    "transfer_count": series.transfer_count,
                    "total_dose_mj_cm2": series.total_dose_mj_cm2,
                    "average_pulse_dose_mj_cm2": series.average_pulse_dose_mj_cm2,
                    "calibration_profile_id": series.calibration_profile_id,
                    "calibration_revision": series.calibration_revision,
                    "calibration_name": series.calibration_name,
                    "calibration_hash": series.calibration_hash,
                    "completeness": {
                        "snapshot_count": series.completeness.snapshot_count,
                        "included_snapshot_count": series.completeness.included_snapshot_count,
                        "excluded_snapshot_count": series.completeness.excluded_snapshot_count,
                        "unknown_eligibility_snapshot_count": (
                            series.completeness.unknown_eligibility_snapshot_count
                        ),
                        "unknown_step_mode_snapshot_count": (
                            series.completeness.unknown_step_mode_snapshot_count
                        ),
                    },
                    "issues": series.issues,
                }
                for series in comparison.series
            ),
            errors=comparison.errors,
            resolution=comparison.resolution,
            wall_origin_quality=comparison.wall_origin_quality,
        )

    @app.post("/api/v1/experiments/{run_id}/dose-series/ensure", response_model=RunDoseSeriesResponse)
    def ensure_run_dose_series(
        run_id: UUID,
        response: Response,
        time_mode: str = Query(default="runtime", pattern="^(runtime|wall)$"),
        resolution: str = Query(default="full", pattern="^(full|thumbnail)$"),
    ) -> RunDoseSeriesResponse:
        try:
            series = experiment_repository.ensure_run_dose_series(
                run_id,
                time_mode=time_mode,
                resolution=resolution,
            )
        except Exception as exc:
            raise _experiment_error_to_http(exc) from exc
        if series.status in {"waiting_for_completion", "busy"}:
            response.status_code = status.HTTP_202_ACCEPTED
        return _run_dose_series_response(series)

    def _run_dose_series_response(series) -> RunDoseSeriesResponse:
        return RunDoseSeriesResponse(
            run_id=series.run_id,
            status=series.status,
            points=tuple(
                {
                    "wall_elapsed_seconds": point.wall_elapsed_seconds,
                    "runtime_seconds": point.runtime_seconds,
                    "dose_increment_mj_cm2": point.dose_increment_mj_cm2,
                    "cumulative_dose_mj_cm2": point.cumulative_dose_mj_cm2,
                    "dose_rate_mj_cm2_s": point.dose_rate_mj_cm2_s,
                    "source_index": point.source_index,
                    "source_sequence": point.source_sequence,
                    "represented_pulse_count": point.represented_pulse_count,
                }
                for point in series.points
            ),
            errors=series.errors,
            source="persisted",
            resolution=series.resolution,
            raw_pulse_count=series.raw_pulse_count,
            runtime_basis=series.runtime_basis,
            time_mode=series.time_mode,
            annotations=tuple(
                {
                    "event_id": annotation.event_id,
                    "category": annotation.category,
                    "kind": annotation.kind,
                    "label": annotation.label,
                    "x": annotation.x,
                    "x_end": annotation.x_end,
                    "value": annotation.value,
                    "source": annotation.source,
                    "producer_unix_ns": annotation.producer_unix_ns,
                    "projection_quality": annotation.projection_quality,
                }
                for annotation in series.annotations
            ),
            issues=series.issues,
            source_kind=series.source_kind,
            source_id=series.source_id,
        )

    @app.get(
        "/api/v1/experiments/{run_id}/snapshots/{snapshot_id}/analysis",
        response_model=SnapshotAnalysisResponse,
    )
    def get_snapshot_analysis(run_id: UUID, snapshot_id: UUID) -> SnapshotAnalysisResponse:
        try:
            analysis = experiment_repository.get_snapshot_analysis(run_id, snapshot_id)
        except Exception as exc:
            raise _experiment_error_to_http(exc) from exc
        return SnapshotAnalysisResponse(
            average_pulse_dose_mj_cm2=analysis.average_pulse_dose_mj_cm2,
            total_dose_mj_cm2=analysis.total_dose_mj_cm2,
            delivered_dose_rate_mj_cm2_s=analysis.delivered_dose_rate_mj_cm2_s,
            pulse_span_seconds=analysis.pulse_span_seconds,
            wall_duration_seconds=analysis.wall_duration_seconds,
            effective_duration_seconds=analysis.effective_duration_seconds,
            runtime_contribution_seconds=analysis.runtime_contribution_seconds,
            is_step_exposure=analysis.is_step_exposure,
            step_mode_source=analysis.step_mode_source,
            metadata_backfilled=analysis.metadata_backfilled,
            backfill_error=analysis.backfill_error,
        )

    @app.get(
        "/api/v1/experiments/{run_id}/snapshots/{snapshot_id}/series/{series}",
        response_model=SnapshotGraphSeriesResponse,
    )
    def get_snapshot_series(
        run_id: UUID,
        snapshot_id: UUID,
        series: str,
        rolling_window: int = Query(default=1),
        time_mode: str = Query(default="wall", pattern="^(wall|apparent)$"),
    ) -> SnapshotGraphSeriesResponse:
        try:
            graph = experiment_repository.get_snapshot_series(
                run_id,
                snapshot_id,
                series,
                rolling_window=rolling_window,
                time_mode=time_mode,
            )
        except Exception as exc:
            raise _experiment_error_to_http(exc) from exc
        return SnapshotGraphSeriesResponse(
            snapshot_id=graph.snapshot_id,
            series=graph.series,
            x_label=graph.x_label,
            y_label=graph.y_label,
            x=graph.x,
            y=graph.y,
            point_count=graph.point_count,
            rolling_window=graph.rolling_window,
            annotations=tuple(
                {
                    "event_id": annotation.event_id,
                    "category": annotation.category,
                    "kind": annotation.kind,
                    "label": annotation.label,
                    "x": annotation.x,
                    "x_end": annotation.x_end,
                    "value": annotation.value,
                    "source": annotation.source,
                    "producer_unix_ns": annotation.producer_unix_ns,
                    "projection_quality": annotation.projection_quality,
                }
                for annotation in graph.annotations
            ),
            issues=graph.issues,
        )

    @app.get("/api/v1/experiments/{run_id}/resources/{resource_name}")
    def download_experiment_resource(
        run_id: UUID,
        resource_name: str,
        range_header: Annotated[str | None, Header(alias="Range")] = None,
    ) -> StreamingResponse:
        try:
            open_resource = experiment_repository.open_resource(run_id, resource_name)
        except Exception as exc:
            raise _experiment_error_to_http(exc) from exc
        try:
            selected_range = _parse_resource_range(range_header, open_resource.resource.size_bytes)
        except HTTPException:
            open_resource.close()
            raise
        if selected_range is None:
            start, end = 0, open_resource.resource.size_bytes - 1
            response_status = status.HTTP_200_OK
        else:
            start, end = selected_range
            response_status = status.HTTP_206_PARTIAL_CONTENT
        length = max(0, end - start + 1)
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Disposition": f'attachment; filename="{open_resource.resource.name}"',
        }
        if selected_range is not None:
            headers["Content-Range"] = f"bytes {start}-{end}/{open_resource.resource.size_bytes}"
        return StreamingResponse(
            _stream_open_resource(open_resource, start, length),
            status_code=response_status,
            media_type="application/octet-stream",
            headers=headers,
        )

    @app.get("/api/v1/logs/archives", response_model=LogArchivesResponse)
    def get_log_archives() -> LogArchivesResponse:
        if log_repository is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Log browser is not configured.")
        try:
            archives = log_repository.list_archives()
        except Exception as exc:
            raise _log_error_to_http(exc) from exc
        return LogArchivesResponse(
            items=tuple(
                LogArchiveResponse(
                    name=archive.name,
                    is_current=archive.is_current,
                    start_line=archive.start_line,
                    end_line_exclusive=archive.end_line_exclusive,
                    start_timestamp=archive.start_timestamp,
                    end_timestamp=archive.end_timestamp,
                )
                for archive in archives
            )
        )

    @app.get("/api/v1/logs/entries", response_model=LogPageResponse)
    def get_log_entries(
        archive: str = Query(default="current", min_length=1, max_length=128),
        direction: Literal["head", "tail", "before", "after"] = Query(default="tail"),
        anchor_line: int | None = Query(default=None, ge=0),
        page_size: int = Query(default=100, ge=50, le=100),
        origin_uuid: str | None = Query(default=None, max_length=128),
        l_type: str | None = Query(default=None, max_length=64),
        level: str | None = Query(default=None, max_length=32),
        min_level: str | None = Query(default=None, max_length=32),
        exclude_type: list[str] | None = Query(default=None),
        include_records: bool = Query(default=False),
        line_from: int | None = Query(default=None, ge=0),
        line_to: int | None = Query(default=None, ge=0),
        since: float | None = None,
        until: float | None = None,
    ) -> LogPageResponse:
        if log_repository is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Log browser is not configured.")
        try:
            page = log_repository.get_page(
                archive,
                LogFilters(
                    origin_uuid=origin_uuid,
                    l_type=l_type,
                    level=level,
                    min_level=min_level,
                    exclude_types=tuple(exclude_type) if exclude_type else (() if include_records else None),
                    line_from=line_from,
                    line_to=line_to,
                    since=since,
                    until=until,
                ),
                direction=direction,
                anchor_line=anchor_line,
                page_size=page_size,
            )
        except Exception as exc:
            raise _log_error_to_http(exc) from exc
        return LogPageResponse(
            archive=page.archive,
            filters=_log_filters_response(page.filters),
            rows=tuple(
                LogEntryResponse(
                    line=row.line,
                    timestamp=row.timestamp,
                    origin_uuid=row.origin_uuid,
                    l_type=row.l_type,
                    level=row.level,
                    subsystem=row.subsystem,
                    message=row.message,
                    record=row.record,
                )
                for row in page.rows
            ),
            first_line=page.first_line,
            last_line=page.last_line,
            has_before=page.has_before,
            has_after=page.has_after,
            at_tail=page.at_tail,
        )

    @app.get("/api/v1/logs/events", response_model=LogEventsResponse)
    def get_log_events(
        archive: str = Query(default="current", min_length=1, max_length=128),
        limit: int = Query(default=200, ge=1, le=200),
    ) -> LogEventsResponse:
        if log_repository is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Log browser is not configured.")
        try:
            events = log_repository.list_events(archive, limit=limit)
        except Exception as exc:
            raise _log_error_to_http(exc) from exc
        return LogEventsResponse(
            items=tuple(
                LogEventResponse(
                    event_id=event.event_id,
                    e_type=event.e_type,
                    level=event.level,
                    message=event.message,
                    start_line=event.start_line,
                    end_line=event.end_line,
                    start_timestamp=event.start_timestamp,
                    end_timestamp=event.end_timestamp,
                    data_start=event.data_start,
                    data_end=event.data_end,
                )
                for event in events
            )
        )

    @app.get("/api/v1/logs/context", response_model=LogContextResponse)
    def get_log_context(
        event_id: str | None = Query(default=None, max_length=128),
        created_at: float | None = None,
        ended_at: float | None = None,
    ) -> LogContextResponse:
        if log_repository is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Log browser is not configured.")
        try:
            context = log_repository.resolve_context(
                event_id=event_id,
                created_at=created_at,
                ended_at=ended_at,
            )
        except Exception as exc:
            raise _log_error_to_http(exc) from exc
        return LogContextResponse(
            resolution=context.resolution,
            archive=context.archive,
            line_from=context.line_from,
            line_to=context.line_to,
            since=context.since,
            until=context.until,
            matching_archives=context.matching_archives,
            message=context.message,
        )

    @app.get("/api/v1/live/events")
    async def get_live_events(
        request: Request,
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        cursor = _parse_last_event_id(last_event_id)
        return StreamingResponse(
            sse_stream(
                request,
                store,
                after_event_id=cursor,
                heartbeat_interval=settings.sse_heartbeat_interval,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/health/live", response_model=HealthResponse)
    async def health_live() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/health/ready", response_model=HealthResponse)
    async def health_ready(response: Response) -> HealthResponse:
        snapshot = await store.latest()
        if snapshot is None:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return HealthResponse(status="starting")
        readiness = "ready" if snapshot.system.state.value == "ok" else "degraded"
        return HealthResponse(status=readiness, system_state=snapshot.system.state)

    return app
