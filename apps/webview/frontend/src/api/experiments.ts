import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { getJson, postJson } from './client'

export type ExperimentFilters = {
  name?: string
  created_min?: number
  created_max?: number
  min_actual_dose?: number
  max_actual_dose?: number
  min_target_dose?: number
  max_target_dose?: number
  min_runtime?: number
  max_runtime?: number
  zr_filter?: string
  sample?: string
  operator?: string
}

export type ExperimentFilterOptions = {
  schema_version: '1'
  samples: string[]
  operators: string[]
  zr_filters: string[]
  actual_dose_min: number | null
  actual_dose_max: number | null
  target_dose_min: number | null
  target_dose_max: number | null
  runtime_min: number | null
  runtime_max: number | null
  created_min: number | null
  created_max: number | null
}

export type ExperimentItem = {
  run_id: string
  created_at: number
  name: string
  description: string
  sample: string | null
  operator: string | null
  zr_filter: string | null
  target_dose: number | null
  target_time: number | null
  actual_dose: number | null
  runtime: number | null
  effective_dose_rate: number | null
  exposed_thickness_nm: number | null
  blank_thickness_nm: number | null
  percent_development: number | null
  status: string | null
  end_reason: string | null
}

export type RegisteredResource = {
  name: string
  resource_type: string
  size_bytes: number | null
  available: boolean
  downloadable: boolean
  error: string | null
}
export type ExperimentDataIssue = {
  section: string
  resource_name: string | null
  kind: string
  message: string
}
export type MetricMeasurement = { spot_type: 'exposed' | 'blank'; thickness_nm: number; goodness_of_fit: number }
export type ExperimentMetrics = {
  measurements: MetricMeasurement[]
  exposed_average_nm: number | null
  blank_average_nm: number | null
  percent_development: number | null
  degraded: boolean
  error: string | null
}
export type Snapshot = {
  snapshot_id: string
  format: 'legacy_npz' | 'euv_hdf5'
  waveform: RegisteredResource
  metadata: RegisteredResource | null
  final_sequence: number | null
}
export type SnapshotAnalysis = {
  average_pulse_dose_mj_cm2: number
  total_dose_mj_cm2: number
  delivered_dose_rate_mj_cm2_s: number
  pulse_span_seconds: number
  wall_duration_seconds: number
  effective_duration_seconds: number
  runtime_contribution_seconds: number
  is_step_exposure: boolean
  step_mode_source: 'provided' | 'inferred' | 'native'
  metadata_backfilled: boolean
  backfill_error: string | null
}
export type SnapshotSeriesKind = 'voltage' | 'peaks' | 'dose'
export type SnapshotTimeMode = 'wall' | 'apparent'
export type RunTimeMode = 'runtime' | 'wall'
export type RunGraphResolution = 'full' | 'thumbnail'
export type GraphAnnotationCategory = 'lifecycle' | 'triggers' | 'transmitting'
export type GraphAnnotation = {
  event_id: string
  category: GraphAnnotationCategory
  kind: 'point' | 'interval'
  label: string
  x: number
  x_end: number | null
  value: boolean | null
  source: string
  producer_unix_ns: number
  projection_quality: 'producer' | 'runtime_hint' | 'exact' | 'next_pulse'
}
export type SnapshotGraphSeries = {
  schema_version: '2'
  snapshot_id: string
  series: SnapshotSeriesKind
  x_label: string
  y_label: string
  x: number[]
  y: number[]
  point_count: number
  rolling_window: number
  annotations: GraphAnnotation[]
  issues: string[]
}
export type RunDoseSeries = {
  schema_version: '3'
  run_id: string
  status: 'waiting_for_completion' | 'missing' | 'busy' | 'complete' | 'error'
  points: {
    wall_elapsed_seconds: number
    runtime_seconds: number
    dose_increment_mj_cm2: number
    cumulative_dose_mj_cm2: number
    dose_rate_mj_cm2_s: number
    source_index: number
    source_sequence: number | null
    represented_pulse_count: number
  }[]
  errors: string[]
  source: 'persisted'
  resolution: RunGraphResolution
  raw_pulse_count: number
  runtime_basis: string | null
  time_mode: RunTimeMode
  annotations: GraphAnnotation[]
  issues: string[]
}
export type ObserverDoseComparison = {
  schema_version: '1'
  run_id: string
  status: 'missing' | 'complete'
  series: {
    session_id: string
    source_kind: string
    source_id: string
    algorithm: 'captured' | 'legacy_compensated'
    algorithm_version: string
    status: 'complete' | 'incomplete'
    points: {
      wall_elapsed_seconds: number
      dose_increment_mj_cm2: number
      cumulative_dose_mj_cm2: number
      source_sequence: number | null
      represented_pulse_count: number
    }[]
    raw_point_count: number
    pulse_count: number
    transfer_count: number
    total_dose_mj_cm2: number
    average_pulse_dose_mj_cm2: number
    calibration_profile_id: string
    calibration_revision: number
    calibration_name: string
    calibration_hash: string
    completeness: {
      snapshot_count: number
      included_snapshot_count: number
      excluded_snapshot_count: number
      unknown_eligibility_snapshot_count: number
      unknown_step_mode_snapshot_count: number
    }
    issues: string[]
  }[]
  errors: string[]
  resolution: RunGraphResolution
  wall_origin_quality: 'unavailable' | 'observer_first_capture' | 'run_preinit'
}
export type ExposureEventTimeline = {
  schema_version: '1'
  run_id: string
  events: {
    event_id: string
    stream_id: string
    stream_name: string
    sequence: number
    kind: string
    producer_unix_ns: number
    producer_monotonic_ns: number | null
    ingest_unix_ns: number
    payload: Record<string, unknown>
    capture_session_id: string | null
    next_sequence: number | null
    runtime_seconds: number | null
  }[]
  complete: boolean
  issues: string[]
  wall_time_origin_unix_ns: number | null
}

export type ExperimentPage = {
  schema_version: '1'
  page: number
  page_size: number
  total_count: number
  total_pages: number
  filters: ExperimentFilters
  items: ExperimentItem[]
}

export type ExperimentDetail = {
  schema_version: '1'
  summary: ExperimentItem
  settings: Record<string, unknown>
  metadata: Record<string, unknown>
  end_metadata: Record<string, unknown> | null
  tags: Record<string, string | number>
  resources: RegisteredResource[]
  snapshots: Snapshot[]
  metrics: ExperimentMetrics
  log_range: { event_id: string; created_at: number | null; ended_at: number | null; complete: boolean }
  issues: ExperimentDataIssue[]
}

function queryString(page: number, pageSize: number, filters: ExperimentFilters): string {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== '') params.set(key, String(value))
  })
  return params.toString()
}

export function fetchExperiments(page: number, pageSize: number, filters: ExperimentFilters, signal?: AbortSignal) {
  return getJson<ExperimentPage>(`/api/v1/experiments?${queryString(page, pageSize, filters)}`, signal)
}

export function fetchExperiment(runId: string, signal?: AbortSignal) {
  return getJson<ExperimentDetail>(`/api/v1/experiments/${encodeURIComponent(runId)}`, signal)
}

export function fetchExperimentFilterOptions(signal?: AbortSignal) {
  return getJson<ExperimentFilterOptions>('/api/v1/experiments/options', signal)
}

export function fetchSnapshotAnalysis(runId: string, snapshotId: string, signal?: AbortSignal) {
  return getJson<SnapshotAnalysis & { schema_version: '1' }>(
    `/api/v1/experiments/${encodeURIComponent(runId)}/snapshots/${encodeURIComponent(snapshotId)}/analysis`,
    signal,
  )
}

export function fetchExposureEvents(runId: string, signal?: AbortSignal) {
  return getJson<ExposureEventTimeline>(`/api/v1/experiments/${encodeURIComponent(runId)}/events`, signal)
}

export function useExperiments(page: number, pageSize: number, filters: ExperimentFilters) {
  return useQuery({
    queryKey: ['experiments', page, pageSize, filters],
    queryFn: ({ signal }) => fetchExperiments(page, pageSize, filters, signal),
    placeholderData: keepPreviousData,
  })
}

export function useExperimentFilterOptions() {
  return useQuery({
    queryKey: ['experiment-filter-options'],
    queryFn: ({ signal }) => fetchExperimentFilterOptions(signal),
    staleTime: 5 * 60 * 1000,
  })
}

export function useExperiment(runId: string) {
  const [availabilityRetries, setAvailabilityRetries] = useState(0)
  const query = useQuery({
    queryKey: ['experiment', runId],
    queryFn: ({ signal }) => fetchExperiment(runId, signal),
    enabled: Boolean(runId),
    retry: 4,
    retryDelay: (attempt) => Math.min(400 * 2 ** attempt, 3000),
  })
  const { data, dataUpdatedAt, isFetching, refetch } = query
  const hasUnavailableData = data?.issues.some((issue) => issue.kind === 'unavailable') ?? false

  useEffect(() => {
    setAvailabilityRetries(0)
  }, [runId])

  useEffect(() => {
    if (!hasUnavailableData || isFetching || availabilityRetries >= 4) return
    const timeout = window.setTimeout(() => {
      setAvailabilityRetries((current) => current + 1)
      void refetch()
    }, Math.min(750 * 2 ** availabilityRetries, 5000))
    return () => window.clearTimeout(timeout)
  }, [availabilityRetries, dataUpdatedAt, hasUnavailableData, isFetching, refetch])

  return query
}

export function useSnapshotAnalysis(runId: string, snapshotId: string | null) {
  return useQuery({
    queryKey: ['experiment-snapshot-analysis', runId, snapshotId],
    queryFn: ({ signal }) => fetchSnapshotAnalysis(runId, snapshotId!, signal),
    enabled: snapshotId !== null,
  })
}

export function useExposureEvents(runId: string) {
  return useQuery({
    queryKey: ['experiment-events', runId],
    queryFn: ({ signal }) => fetchExposureEvents(runId, signal),
    enabled: Boolean(runId),
    staleTime: Number.POSITIVE_INFINITY,
  })
}

export function fetchSnapshotSeries(
  runId: string,
  snapshotId: string,
  series: SnapshotSeriesKind,
  rollingWindow: number,
  timeMode: SnapshotTimeMode = 'wall',
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({ rolling_window: String(rollingWindow), time_mode: timeMode })
  return getJson<SnapshotGraphSeries>(
    `/api/v1/experiments/${encodeURIComponent(runId)}/snapshots/${encodeURIComponent(snapshotId)}/series/${series}?${params}`,
    signal,
    ['2'],
  )
}

export function useSnapshotSeries(
  runId: string,
  snapshotId: string | null,
  series: SnapshotSeriesKind,
  rollingWindow: number,
  timeMode: SnapshotTimeMode = 'wall',
) {
  return useQuery({
    queryKey: ['experiment-snapshot-series', runId, snapshotId, series, rollingWindow, timeMode],
    queryFn: ({ signal }) => fetchSnapshotSeries(runId, snapshotId!, series, rollingWindow, timeMode, signal),
    enabled: snapshotId !== null,
    staleTime: Number.POSITIVE_INFINITY,
    retry: 2,
  })
}

export function fetchRunDoseSeries(
  runId: string,
  timeMode: RunTimeMode = 'runtime',
  resolution: RunGraphResolution = 'full',
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({ time_mode: timeMode, resolution })
  return getJson<RunDoseSeries>(`/api/v1/experiments/${encodeURIComponent(runId)}/dose-series?${params}`, signal, ['3'])
}

export function ensureRunDoseSeries(
  runId: string,
  timeMode: RunTimeMode = 'runtime',
  resolution: RunGraphResolution = 'full',
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({ time_mode: timeMode, resolution })
  return postJson<RunDoseSeries>(`/api/v1/experiments/${encodeURIComponent(runId)}/dose-series/ensure?${params}`, signal, ['3'])
}

export function fetchObserverDoseComparison(
  runId: string,
  resolution: RunGraphResolution = 'full',
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({ resolution })
  return getJson<ObserverDoseComparison>(
    `/api/v1/experiments/${encodeURIComponent(runId)}/observer-dose-series?${params}`,
    signal,
    ['1'],
  )
}

export function useObserverDoseComparison(runId: string, resolution: RunGraphResolution = 'full') {
  return useQuery({
    queryKey: ['experiment-observer-dose-series', runId, resolution],
    queryFn: ({ signal }) => fetchObserverDoseComparison(runId, resolution, signal),
    enabled: Boolean(runId),
    staleTime: Number.POSITIVE_INFINITY,
    retry: 2,
  })
}

export function useRunDoseSeries(
  runId: string,
  timeMode: RunTimeMode = 'runtime',
  resolution: RunGraphResolution = 'full',
) {
  const queryClient = useQueryClient()
  const queryKey = ['experiment-run-dose-series', runId, timeMode, resolution] as const
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) => fetchRunDoseSeries(runId, timeMode, resolution, signal),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'missing' || status === 'waiting_for_completion' || status === 'busy' ? 1000 : false
    },
    staleTime: Number.POSITIVE_INFINITY,
  })
  const repair = useMutation({
    mutationFn: () => ensureRunDoseSeries(runId, timeMode, resolution),
    onSuccess: (series) => queryClient.setQueryData(queryKey, series),
  })
  useEffect(() => {
    if (query.data?.status === 'missing' && !repair.isPending && !repair.isError) repair.mutate()
  }, [query.data?.status, repair.isError, repair.isPending, repair.mutate])
  return { ...query, error: query.error ?? repair.error }
}

export function useRunComparisons(runIds: string[]) {
  const details = useQueries({
    queries: runIds.map((runId) => ({
      queryKey: ['experiment', runId],
      queryFn: ({ signal }: { signal: AbortSignal }) => fetchExperiment(runId, signal),
      staleTime: 5 * 60 * 1000,
    })),
  })
  const series = useQueries({
    queries: runIds.map((runId) => ({
      queryKey: ['experiment-run-dose-series', runId, 'runtime', 'thumbnail'],
      queryFn: ({ signal }: { signal: AbortSignal }) => fetchRunDoseSeries(runId, 'runtime', 'thumbnail', signal),
      refetchInterval: (query: { state: { data?: RunDoseSeries } }) => {
        const status = query.state.data?.status
        return status === 'missing' || status === 'waiting_for_completion' || status === 'busy' ? 1000 : false
      },
      staleTime: Number.POSITIVE_INFINITY,
    })),
  })
  return { details, series }
}