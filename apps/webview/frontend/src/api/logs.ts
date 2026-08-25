import { useQuery } from '@tanstack/react-query'

import { getJson } from './client'

export type LogFilters = {
  origin_uuid?: string
  l_type?: string
  level?: string
  min_level?: string
  exclude_types?: string[]
  include_records?: boolean
  line_from?: number
  line_to?: number
  since?: number
  until?: number
}

export type LogArchive = {
  name: string
  is_current: boolean
  start_line: number
  end_line_exclusive: number
  start_timestamp: number | null
  end_timestamp: number | null
}

export type LogEntry = {
  line: number
  timestamp: number | null
  origin_uuid: string | null
  l_type: string
  level: string
  subsystem: string
  message: string
  record: Record<string, unknown>
}

export type LogPage = {
  schema_version: '1'
  archive: string
  filters: {
    origin_uuid: string | null
    l_type: string | null
    level: string | null
    min_level: string | null
    exclude_types: string[] | null
    line_from: number | null
    line_to: number | null
    since: number | null
    until: number | null
  }
  rows: LogEntry[]
  first_line: number | null
  last_line: number | null
  has_before: boolean
  has_after: boolean
  at_tail: boolean
}

export type LogEvent = {
  event_id: string
  e_type: string
  level: string
  message: string
  start_line: number
  end_line: number | null
  start_timestamp: number | null
  end_timestamp: number | null
  data_start: Record<string, unknown>
  data_end: Record<string, unknown>
}

export type LogContext = {
  schema_version: '1'
  resolution: 'event' | 'time' | 'unscoped'
  archive: string | null
  line_from: number | null
  line_to: number | null
  since: number | null
  until: number | null
  matching_archives: string[]
  message: string | null
}

type LogArchivesResponse = { schema_version: '1'; items: LogArchive[] }
type LogEventsResponse = { schema_version: '1'; items: LogEvent[] }

export type LogPageRequest = {
  archive: string
  direction: 'head' | 'tail' | 'before' | 'after'
  anchor_line?: number
  page_size?: number
  filters: LogFilters
}

function addFilters(params: URLSearchParams, filters: LogFilters) {
  if (filters.origin_uuid) params.set('origin_uuid', filters.origin_uuid)
  if (filters.l_type) params.set('l_type', filters.l_type)
  if (filters.level) params.set('level', filters.level)
  if (filters.min_level) params.set('min_level', filters.min_level)
  filters.exclude_types?.forEach((value) => params.append('exclude_type', value))
  if (filters.include_records) params.set('include_records', 'true')
  if (filters.line_from !== undefined) params.set('line_from', String(filters.line_from))
  if (filters.line_to !== undefined) params.set('line_to', String(filters.line_to))
  if (filters.since !== undefined) params.set('since', String(filters.since))
  if (filters.until !== undefined) params.set('until', String(filters.until))
}

export function fetchLogArchives(signal?: AbortSignal) {
  return getJson<LogArchivesResponse>('/api/v1/logs/archives', signal)
}

export function fetchLogEntries(request: LogPageRequest, signal?: AbortSignal) {
  const params = new URLSearchParams({
    archive: request.archive,
    direction: request.direction,
    page_size: String(request.page_size ?? 100),
  })
  if (request.anchor_line !== undefined) params.set('anchor_line', String(request.anchor_line))
  addFilters(params, request.filters)
  return getJson<LogPage>(`/api/v1/logs/entries?${params}`, signal)
}

export function fetchLogEvents(archive: string, signal?: AbortSignal) {
  return getJson<LogEventsResponse>(`/api/v1/logs/events?archive=${encodeURIComponent(archive)}`, signal)
}

export function fetchLogContext(
  context: { event_id?: string; created_at?: number; ended_at?: number },
  signal?: AbortSignal,
) {
  const params = new URLSearchParams()
  if (context.event_id) params.set('event_id', context.event_id)
  if (context.created_at !== undefined) params.set('created_at', String(context.created_at))
  if (context.ended_at !== undefined) params.set('ended_at', String(context.ended_at))
  return getJson<LogContext>(`/api/v1/logs/context?${params}`, signal)
}

export function useLogArchives() {
  return useQuery({
    queryKey: ['log-archives'],
    queryFn: ({ signal }) => fetchLogArchives(signal),
    staleTime: 30_000,
    retry: false,
  })
}

export function useLogEvents(archive: string) {
  return useQuery({
    queryKey: ['log-events', archive],
    queryFn: ({ signal }) => fetchLogEvents(archive, signal),
    enabled: Boolean(archive),
    staleTime: 10_000,
    retry: false,
  })
}

export function useLogContext(context: { event_id?: string; created_at?: number; ended_at?: number }) {
  return useQuery({
    queryKey: ['log-context', context],
    queryFn: ({ signal }) => fetchLogContext(context, signal),
    enabled: Boolean(context.event_id || context.created_at !== undefined || context.ended_at !== undefined),
    staleTime: 60_000,
    retry: false,
  })
}