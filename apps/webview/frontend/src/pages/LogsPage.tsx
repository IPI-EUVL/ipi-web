import { Modal } from '@mantine/core'
import { Archive, Eye, Filter, ListTree, PanelLeft, PanelRight, Radio, RefreshCw, RotateCcw, ScrollText, TriangleAlert, X } from 'lucide-react'
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type UIEventHandler,
} from 'react'

import {
  fetchLogEntries,
  type LogContext,
  type LogEntry,
  type LogEvent,
  type LogFilters,
  type LogPage,
  useLogArchives,
  useLogContext,
  useLogEvents,
} from '../api/logs'
import { ApiError } from '../api/client'

const PAGE_SIZE = 100
const MAX_BUFFERED_PAGES = 5
const MAX_VISIBLE_EVENT_MARKERS = 4
const EMPTY_LOG_EVENTS: LogEvent[] = []

type FilterDraft = {
  originUuid: string
  type: string
  level: string
  minLevel: string
  excludeTypes: string
  lineFrom: string
  lineTo: string
  since: string
  until: string
  includeRecords: boolean
}

type ScrollAnchor = { line: number; offset: number }
type LogPageDirection = 'head' | 'tail' | 'before' | 'after'
type InitialScrollPosition = 'head' | 'tail'
type EventMarkerLayout = {
  event: LogEvent
  top: number
  height: number
  labelTop: number
  lane: number
  isClamped: boolean
}

function numberFromQuery(params: URLSearchParams, key: string): number | undefined {
  const value = params.get(key)
  if (value === null || !value.trim()) return undefined
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

function contextFromSearch(): { event_id?: string; created_at?: number; ended_at?: number } {
  const params = new URLSearchParams(window.location.search)
  const eventId = params.get('event_id')?.trim()
  return {
    event_id: eventId || undefined,
    created_at: numberFromQuery(params, 'created_at'),
    ended_at: numberFromQuery(params, 'ended_at'),
  }
}

function parseOptionalNumber(value: string): number | undefined {
  const parsed = Number(value)
  return value.trim() && Number.isFinite(parsed) ? parsed : undefined
}

function datetimeInputValue(timestamp: number | undefined): string {
  if (timestamp === undefined) return ''
  const date = new Date(timestamp * 1000)
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

function datetimeSeconds(value: string): number | undefined {
  if (!value) return undefined
  const milliseconds = new Date(value).getTime()
  return Number.isFinite(milliseconds) ? milliseconds / 1000 : undefined
}

function emptyDraft(): FilterDraft {
  return {
    originUuid: '',
    type: '',
    level: '',
    minLevel: '',
    excludeTypes: '',
    lineFrom: '',
    lineTo: '',
    since: '',
    until: '',
    includeRecords: false,
  }
}

function draftFromFilters(filters: LogFilters): FilterDraft {
  return {
    originUuid: filters.origin_uuid ?? '',
    type: filters.l_type ?? '',
    level: filters.level ?? '',
    minLevel: filters.min_level ?? '',
    excludeTypes: filters.exclude_types?.join(', ') ?? '',
    lineFrom: filters.line_from?.toString() ?? '',
    lineTo: filters.line_to?.toString() ?? '',
    since: datetimeInputValue(filters.since),
    until: datetimeInputValue(filters.until),
    includeRecords: filters.include_records ?? false,
  }
}

function filtersFromDraft(draft: FilterDraft): LogFilters {
  const excludeTypes = draft.excludeTypes.split(',').map((value) => value.trim()).filter(Boolean)
  return {
    origin_uuid: draft.originUuid.trim() || undefined,
    l_type: draft.type.trim() || undefined,
    level: draft.level.trim() || undefined,
    min_level: draft.minLevel.trim() || undefined,
    exclude_types: excludeTypes.length ? excludeTypes : undefined,
    include_records: draft.includeRecords || undefined,
    line_from: parseOptionalNumber(draft.lineFrom),
    line_to: parseOptionalNumber(draft.lineTo),
    since: datetimeSeconds(draft.since),
    until: datetimeSeconds(draft.until),
  }
}

function filtersFromContext(context: LogContext): LogFilters {
  if (context.resolution === 'event') {
    return { line_from: context.line_from ?? undefined, line_to: context.line_to ?? undefined }
  }
  if (context.resolution === 'time') {
    return { since: context.since ?? undefined, until: context.until ?? undefined }
  }
  return {}
}

function formatTimestamp(timestamp: number | null): string {
  if (timestamp === null) return '—'
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'medium' }).format(timestamp * 1000)
}

function eventRange(start: number, end: number | null): string {
  return end === null || end === start ? String(start) : `${start}–${end}`
}

function eventLabel(event: LogEvent): string {
  return event.message || `${event.e_type} · ${event.level}`
}

function isLogServiceUnavailable(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 503
}

function useBufferedLogPages(
  archive: string,
  filters: LogFilters,
  initialAnchorLine?: number,
  initialDirection?: LogPageDirection,
  initialScrollPosition: InitialScrollPosition = 'tail',
) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const topSentinelRef = useRef<HTMLDivElement>(null)
  const bottomSentinelRef = useRef<HTMLDivElement>(null)
  const restoreAnchorRef = useRef<ScrollAnchor | null>(null)
  const scrollToHeadRef = useRef(false)
  const scrollToTailRef = useRef(false)
  const activeRequestRef = useRef(0)
  const loadingMoreRef = useRef(false)
  const [pages, setPages] = useState<LogPage[]>([])
  const [initialLoading, setInitialLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  const captureScrollAnchor = useCallback(() => {
    const container = scrollRef.current
    if (!container) return null
    const containerTop = container.getBoundingClientRect().top
    const rows = Array.from(container.querySelectorAll<HTMLElement>('[data-log-line]'))
    const row = rows.find((candidate) => candidate.getBoundingClientRect().bottom > containerTop)
    if (!row?.dataset.logLine) return null
    return { line: Number(row.dataset.logLine), offset: row.getBoundingClientRect().top - containerTop }
  }, [])

  useLayoutEffect(() => {
    const container = scrollRef.current
    const anchor = restoreAnchorRef.current
    if (container && anchor) {
      const row = Array.from(container.querySelectorAll<HTMLElement>('[data-log-line]'))
        .find((candidate) => Number(candidate.dataset.logLine) === anchor.line)
      if (row) container.scrollTop += row.getBoundingClientRect().top - container.getBoundingClientRect().top - anchor.offset
      restoreAnchorRef.current = null
    }
    if (container && scrollToTailRef.current) {
      container.scrollTop = container.scrollHeight
      scrollToTailRef.current = false
    }
    if (container && scrollToHeadRef.current) {
      container.scrollTop = 0
      scrollToHeadRef.current = false
    }
  }, [pages])

  const loadTail = useCallback(async (replace = true) => {
    const requestId = ++activeRequestRef.current
    if (replace) {
      setInitialLoading(true)
      setPages([])
    }
    setError(null)
    try {
      const page = await fetchLogEntries({
        archive,
        direction: initialDirection ?? (initialAnchorLine === undefined ? 'tail' : 'before'),
        anchor_line: initialAnchorLine,
        page_size: PAGE_SIZE,
        filters,
      })
      if (requestId !== activeRequestRef.current) return
      if (initialScrollPosition === 'head') scrollToHeadRef.current = true
      else scrollToTailRef.current = true
      setPages([page])
    } catch (reason) {
      if (requestId === activeRequestRef.current) setError(reason instanceof Error ? reason : new Error('Unable to load logs.'))
    } finally {
      if (requestId === activeRequestRef.current) setInitialLoading(false)
    }
  }, [archive, filters, initialAnchorLine, initialDirection, initialScrollPosition])

  useEffect(() => {
    void loadTail()
  }, [loadTail])

  const loadMore = useCallback(async (direction: 'before' | 'after') => {
    if (loadingMoreRef.current || initialLoading) return
    const boundary = direction === 'before' ? pages[0]?.first_line : pages.at(-1)?.last_line
    const available = direction === 'before' ? pages[0]?.has_before : pages.at(-1)?.has_after
    if (boundary === null || boundary === undefined || !available) return
    const requestId = activeRequestRef.current
    loadingMoreRef.current = true
    setLoadingMore(true)
    const scrollAnchor = captureScrollAnchor()
    try {
      const page = await fetchLogEntries({
        archive,
        direction,
        anchor_line: boundary,
        page_size: PAGE_SIZE,
        filters,
      })
      if (requestId !== activeRequestRef.current) return
      if (!page.rows.length) return
      restoreAnchorRef.current = scrollAnchor
      setPages((current) => {
        const duplicate = current.some((existing) => existing.first_line === page.first_line && existing.last_line === page.last_line)
        if (duplicate) return current
        const next = direction === 'before' ? [page, ...current] : [...current, page]
        return direction === 'before' ? next.slice(0, MAX_BUFFERED_PAGES) : next.slice(-MAX_BUFFERED_PAGES)
      })
    } catch (reason) {
      setError(reason instanceof Error ? reason : new Error('Unable to load another log page.'))
    } finally {
      loadingMoreRef.current = false
      setLoadingMore(false)
    }
  }, [archive, captureScrollAnchor, filters, initialLoading, pages])

  useEffect(() => {
    const container = scrollRef.current
    const top = topSentinelRef.current
    const bottom = bottomSentinelRef.current
    if (!container || !top || !bottom) return
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return
        if (entry.target === top) void loadMore('before')
        if (entry.target === bottom) void loadMore('after')
      })
    }, { root: container, rootMargin: '480px 0px' })
    observer.observe(top)
    observer.observe(bottom)
    return () => observer.disconnect()
  }, [loadMore])

  const refreshTail = useCallback(() => {
    void loadTail(false)
  }, [loadTail])
  const resetToTail = useCallback(() => {
    void loadTail(true)
  }, [loadTail])

  return {
    pages,
    rows: pages.flatMap((page) => page.rows),
    scrollRef,
    topSentinelRef,
    bottomSentinelRef,
    initialLoading,
    loadingMore,
    error,
    atTail: pages.at(-1)?.at_tail ?? true,
    refreshTail,
    loadTail: resetToTail,
  }
}

export function ExposureLogView({
  eventId,
  createdAt,
  endedAt,
}: {
  eventId: string
  createdAt: number | null
  endedAt: number | null
}) {
  const context = useLogContext({ event_id: eventId, created_at: createdAt ?? undefined, ended_at: endedAt ?? undefined })
  const resolved = context.data
  const archive = resolved?.archive ?? 'current'
  const filters = resolved?.resolution === 'time' ? filtersFromContext(resolved) : EMPTY_LOG_FILTERS
  const initialAnchorLine = resolved?.resolution === 'event'
    ? (resolved.line_to ?? resolved.line_from ?? undefined) !== undefined
      ? (resolved.line_to ?? resolved.line_from ?? 0) + 1
      : undefined
    : undefined
  const browser = useBufferedLogPages(archive, filters, initialAnchorLine)
  const [selectedEntry, setSelectedEntry] = useState<LogEntry | null>(null)
  const rows = browser.rows
  const unavailableError = [context.error, browser.error].find(isLogServiceUnavailable)

  if (unavailableError) return <p className="inline-notice" role="alert">{unavailableError.message}</p>

  return (
    <section className="log-embedded-view" aria-label="Exposure log records">
      <div className="log-embedded-heading">
        <span>
          <p className="eyebrow">{archive}</p>
          <h2>Exposure log context</h2>
        </span>
        <span className="log-buffer-state">{rows.length.toLocaleString()} rows · {Math.min(MAX_BUFFERED_PAGES, browser.pages.length)} pages</span>
      </div>
      {resolved?.message && <p className="inline-notice">{resolved.message}</p>}
      {browser.error && <p className="inline-notice">{browser.error.message}</p>}
      <LogRecordTable browser={browser} onSelectEntry={setSelectedEntry} embedded />
      <Modal opened={selectedEntry !== null} onClose={() => setSelectedEntry(null)} title={selectedEntry ? `Raw record ${selectedEntry.line.toLocaleString()}` : 'Raw record'} size="xl">
        {selectedEntry && <pre className="log-raw-record">{JSON.stringify(selectedEntry.record, null, 2)}</pre>}
      </Modal>
    </section>
  )
}

function LogRecordTable({
  browser,
  onSelectEntry,
  embedded = false,
  onScroll,
  events = EMPTY_LOG_EVENTS,
  selectedEventId,
}: {
  browser: ReturnType<typeof useBufferedLogPages>
  onSelectEntry: (entry: LogEntry) => void
  embedded?: boolean
  onScroll?: UIEventHandler<HTMLDivElement>
  events?: LogEvent[]
  selectedEventId?: string
}) {
  const rows = browser.rows
  const [eventMarkers, setEventMarkers] = useState<EventMarkerLayout[]>([])

  const updateEventMarkers = useCallback(() => {
    const container = browser.scrollRef.current
    if (!container || !events.length || !rows.length) {
      setEventMarkers((current) => current.length ? [] : current)
      return
    }

    const containerRect = container.getBoundingClientRect()
    const rowBoxes = Array.from(container.querySelectorAll<HTMLElement>('[data-log-line]')).map((row) => ({
      line: Number(row.dataset.logLine),
      top: row.getBoundingClientRect().top - containerRect.top,
      bottom: row.getBoundingClientRect().bottom - containerRect.top,
    }))
    const visibleRows = rowBoxes.filter((row) => row.bottom > 0 && row.top < container.clientHeight)
    if (!visibleRows.length) {
      setEventMarkers((current) => current.length ? [] : current)
      return
    }

    const firstVisibleLine = visibleRows[0].line
    const lastVisibleLine = visibleRows.at(-1)?.line ?? firstVisibleLine
    const visibleEvents = events
      .filter((event) => event.start_line <= lastVisibleLine && (event.end_line ?? Infinity) >= firstVisibleLine)
      .sort((left, right) => {
        if (left.event_id === selectedEventId) return -1
        if (right.event_id === selectedEventId) return 1
        return left.start_line - right.start_line
      })
      .slice(0, MAX_VISIBLE_EVENT_MARKERS)

    const laneEnds: number[] = []
    const markerHeight = container.clientHeight
    const markers = visibleEvents.map((event) => {
      const startRow = rowBoxes.find((row) => row.line >= event.start_line)
      const endRow = event.end_line === null ? undefined : rowBoxes.find((row) => row.line >= event.end_line!)
      const startsAboveViewport = event.start_line < firstVisibleLine
      const endsBelowViewport = event.end_line === null || event.end_line > lastVisibleLine
      const top = startsAboveViewport ? 0 : Math.max(0, Math.min(markerHeight, startRow?.top ?? 0))
      const bottom = endsBelowViewport
        ? markerHeight
        : Math.max(top + 10, Math.min(markerHeight, endRow?.bottom ?? markerHeight))
      const availableLane = laneEnds.findIndex((laneEnd) => laneEnd + 20 < top)
      const lane = availableLane === -1 ? laneEnds.length : availableLane
      laneEnds[lane] = bottom
      const isClamped = endsBelowViewport || bottom + 104 > markerHeight
      return {
        event,
        top,
        height: Math.max(10, bottom - top),
        labelTop: isClamped ? Math.max(4, markerHeight - 104) : Math.min(markerHeight - 104, bottom + 4),
        lane,
        isClamped,
      }
    })
    setEventMarkers(markers)
  }, [browser.scrollRef, events, rows.length, selectedEventId])

  useLayoutEffect(() => {
    updateEventMarkers()
    window.addEventListener('resize', updateEventMarkers)
    return () => window.removeEventListener('resize', updateEventMarkers)
  }, [updateEventMarkers])

  const handleViewportScroll: UIEventHandler<HTMLDivElement> = (event) => {
    onScroll?.(event)
    updateEventMarkers()
  }

  return (
    <div className={`log-scroll ${embedded ? 'is-embedded' : ''} ${events.length ? 'has-event-gutter' : ''}`} ref={browser.scrollRef} onScroll={handleViewportScroll} tabIndex={0} aria-label="Buffered log records">
      {eventMarkers.length > 0 && <div className="log-event-gutter" aria-hidden="true">
        {eventMarkers.map((marker) => (
          <div key={marker.event.event_id} className={`log-gutter-marker ${marker.event.event_id === selectedEventId ? 'is-selected' : ''}`}>
            <span className="log-gutter-line" style={{ top: marker.top, height: marker.height, left: 18 + marker.lane * 16 }} />
            <span className={`log-gutter-label ${marker.isClamped ? 'is-clamped' : ''}`} style={{ top: marker.labelTop, left: 14 + marker.lane * 16 }} title={eventLabel(marker.event)}>{eventLabel(marker.event)}</span>
          </div>
        ))}
      </div>}
      <div className="log-page-sentinel" ref={browser.topSentinelRef}>{browser.loadingMore && 'Loading earlier records…'}</div>
      {browser.initialLoading ? <div className="panel-empty"><ScrollText size={20} aria-hidden="true" />Loading indexed records…</div> : (
        <table className="data-table log-table">
          <thead><tr><th>Line</th><th>Time</th><th>Origin</th><th>Type</th><th>Level</th><th>Subsystem</th><th>Message</th><th aria-label="Record detail" /></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.line} data-log-line={row.line} className={`log-record log-record-level-${row.level.toLowerCase()} log-record-type-${row.l_type.toLowerCase()}`}>
                <td className="numeric-cell log-line">{row.line.toLocaleString()}</td>
                <td className="log-time">{formatTimestamp(row.timestamp)}</td>
                <td className="log-origin" title={row.origin_uuid ?? undefined}>{row.origin_uuid?.slice(-8) ?? '—'}</td>
                <td><span className="log-type">{row.l_type}</span></td>
                <td><span className={`log-level log-level-${row.level.toLowerCase()}`}>{row.level}</span></td>
                <td className="log-subsystem">{row.subsystem}</td>
                <td className="log-message">{row.message || '—'}</td>
                <td><button type="button" className="icon-action log-detail-action" onClick={() => onSelectEntry(row)} title={`View raw record ${row.line}`} aria-label={`View raw record ${row.line}`}><Eye size={16} aria-hidden="true" /></button></td>
              </tr>
            ))}
            {!rows.length && !browser.error && <tr><td colSpan={8} className="result-cell">No indexed records match these filters.</td></tr>}
          </tbody>
        </table>
      )}
      <div className="log-page-sentinel" ref={browser.bottomSentinelRef}>{browser.loadingMore && 'Loading later records…'}</div>
    </div>
  )
}

const EMPTY_LOG_FILTERS: LogFilters = {}

export function LogsPage() {
  const initialContext = contextFromSearch()
  const archives = useLogArchives()
  const context = useLogContext(initialContext)
  const [archive, setArchive] = useState('current')
  const [filters, setFilters] = useState<LogFilters>({})
  const [draft, setDraft] = useState<FilterDraft>(emptyDraft)
  const [follow, setFollow] = useState(true)
  const [selectedEntry, setSelectedEntry] = useState<LogEntry | null>(null)
  const [showFilters, setShowFilters] = useState(true)
  const [showEvents, setShowEvents] = useState(true)
  const [selectedEvent, setSelectedEvent] = useState<LogEvent | null>(null)
  const appliedContextRef = useRef('')
  const filtersBeforeEventRef = useRef<{ filters: LogFilters; draft: FilterDraft } | null>(null)
  const events = useLogEvents(archive)
  const eventInitialDirection: LogPageDirection | undefined = selectedEvent
    ? selectedEvent.start_line === 0 ? 'head' : 'after'
    : undefined
  const eventInitialAnchorLine = selectedEvent && selectedEvent.start_line > 0
    ? selectedEvent.start_line - 1
    : undefined
  const browser = useBufferedLogPages(archive, filters, eventInitialAnchorLine, eventInitialDirection, selectedEvent ? 'head' : 'tail')
  const { atTail, refreshTail } = browser

  useEffect(() => {
    const resolved = context.data
    if (!resolved) return
    const contextKey = JSON.stringify(resolved)
    if (appliedContextRef.current === contextKey) return
    appliedContextRef.current = contextKey
    const nextFilters = filtersFromContext(resolved)
    if (resolved.archive) setArchive(resolved.archive)
    setFilters(nextFilters)
    setDraft(draftFromFilters(nextFilters))
    setFollow(resolved.archive === 'current')
  }, [context.data])

  useEffect(() => {
    if (!follow || archive !== 'current' || !atTail) return
    const interval = window.setInterval(refreshTail, 2_000)
    return () => window.clearInterval(interval)
  }, [archive, atTail, follow, refreshTail])

  const updateDraft = <Key extends keyof FilterDraft>(key: Key, value: FilterDraft[Key]) => {
    setDraft((current) => ({ ...current, [key]: value }))
  }

  const applyFilters = () => {
    const nextFilters = filtersFromDraft(draft)
    filtersBeforeEventRef.current = null
    setSelectedEvent(null)
    setFilters(nextFilters)
    setFollow(archive === 'current')
  }

  const clearFilters = () => {
    const nextDraft = emptyDraft()
    filtersBeforeEventRef.current = null
    setSelectedEvent(null)
    setDraft(nextDraft)
    setFilters({})
    setFollow(archive === 'current')
  }

  const selectArchive = (nextArchive: string) => {
    if (selectedEvent) {
      const prior = filtersBeforeEventRef.current
      if (prior) {
        setFilters(prior.filters)
        setDraft(prior.draft)
      }
      filtersBeforeEventRef.current = null
      setSelectedEvent(null)
    }
    setArchive(nextArchive)
    setFollow(nextArchive === 'current')
  }

  const selectEvent = (event: LogEvent) => {
    if (!selectedEvent) filtersBeforeEventRef.current = { filters, draft }
    const baseFilters = filtersBeforeEventRef.current?.filters ?? filters
    const nextFilters = { ...baseFilters, line_from: undefined, line_to: undefined }
    setFilters(nextFilters)
    setDraft(draftFromFilters(nextFilters))
    setSelectedEvent(event)
    setFollow(false)
  }

  const clearSelectedEvent = () => {
    const prior = filtersBeforeEventRef.current
    const nextFilters = prior?.filters ?? { ...filters, line_from: undefined, line_to: undefined }
    setFilters(nextFilters)
    setDraft(prior?.draft ?? draftFromFilters(nextFilters))
    filtersBeforeEventRef.current = null
    setSelectedEvent(null)
    setFollow(archive === 'current')
  }

  const filterByOriginUuid = (originUuid: string) => {
    const nextFilters = { ...filters, origin_uuid: originUuid }
    filtersBeforeEventRef.current = null
    setSelectedEvent(null)
    setFilters(nextFilters)
    setDraft(draftFromFilters(nextFilters))
    setFollow(false)
    setSelectedEntry(null)
  }

  const handleScroll = () => {
    const element = browser.scrollRef.current
    if (!element || archive !== 'current') return
    if (element.scrollHeight - element.scrollTop - element.clientHeight > 32) setFollow(false)
  }

  const followTail = () => {
    setFollow(true)
    void browser.loadTail()
  }

  const statusMessage = context.data?.message ?? (context.error instanceof Error ? context.error.message : null)
  const rows = browser.rows
  const unavailableError = [archives.error, context.error, events.error, browser.error].find(isLogServiceUnavailable)

  if (unavailableError) {
    const isUnconfigured = unavailableError.message === 'Log browser is not configured.'
    return (
      <div className="page page-enter">
        <section className="log-unavailable-page" role="alert">
          <TriangleAlert size={28} aria-hidden="true" />
          <div>
            <p className="eyebrow">ECS journal</p>
            <h1>Log browser unavailable</h1>
            <p>{isUnconfigured
              ? 'Set IPI_ECS_LOG_DIR on the API process to the ECS log root. WEBVIEW_LOG_PATH remains available as an explicit override.'
              : unavailableError.message}</p>
          </div>
        </section>
      </div>
    )
  }

  return (
    <div className="page page-enter logs-page">
      <section className="page-heading logs-heading">
        <div>
          <p className="eyebrow">Indexed ECS journal</p>
          <h1>Logs</h1>
          <p>Live and archived system records with full structured detail.</p>
        </div>
        <div className="log-heading-actions">
          <button type="button" className={`icon-action ${showFilters ? 'is-active' : ''}`} onClick={() => setShowFilters((visible) => !visible)} title={showFilters ? 'Hide archives and filters' : 'Show archives and filters'} aria-label={showFilters ? 'Hide archives and filters' : 'Show archives and filters'}>
            <PanelLeft size={16} aria-hidden="true" />
          </button>
          <button type="button" className={`icon-action ${showEvents ? 'is-active' : ''}`} onClick={() => setShowEvents((visible) => !visible)} title={showEvents ? 'Hide event markers' : 'Show event markers'} aria-label={showEvents ? 'Hide event markers' : 'Show event markers'}>
            <PanelRight size={16} aria-hidden="true" />
          </button>
          <button type="button" className={`quiet-action ${follow ? 'is-active' : ''}`} onClick={followTail} disabled={archive !== 'current'}>
            <Radio size={15} aria-hidden="true" />Follow tail
          </button>
          <button type="button" className="icon-action" onClick={() => void browser.loadTail()} title="Refresh log tail" aria-label="Refresh log tail">
            <RefreshCw size={16} aria-hidden="true" />
          </button>
        </div>
      </section>

      {statusMessage && <p className="inline-notice">{statusMessage}</p>}

      <section className={`log-browser-layout ${showFilters ? 'has-left-sidebar' : ''} ${showEvents ? 'has-right-sidebar' : ''}`}>
        {showFilters && <aside className="panel log-sidebar" aria-label="Log archive and filters">
          <div className="panel-heading"><div><p className="eyebrow">Archives</p><h2>Journal source</h2></div><Archive size={17} aria-hidden="true" /></div>
          {archives.error && <p className="inline-notice">{archives.error.message}</p>}
          <div className="log-archive-list">
            {archives.data?.items.map((item) => (
              <button type="button" key={item.name} className={archive === item.name ? 'is-active' : ''} onClick={() => selectArchive(item.name)}>
                <span><strong>{item.name}</strong><small>{item.is_current ? 'Active journal' : `${item.start_line.toLocaleString()}–${Math.max(item.start_line, item.end_line_exclusive - 1).toLocaleString()}`}</small></span>
                {item.is_current && <span className="archive-live-dot" aria-label="Active" />}
              </button>
            ))}
            {archives.isLoading && <span className="muted">Loading archives…</span>}
          </div>
          <details className="log-filter-details" open>
            <summary><Filter size={15} aria-hidden="true" />Filters</summary>
            <div className="log-filter-body">
              <div className="log-filter-fields">
                <label>Origin UUID<input value={draft.originUuid} onChange={(event) => updateDraft('originUuid', event.target.value)} /></label>
                <label>Type<input placeholder="EXP" value={draft.type} onChange={(event) => updateDraft('type', event.target.value)} /></label>
                <label>Exact level<input placeholder="INFO" value={draft.level} onChange={(event) => updateDraft('level', event.target.value)} /></label>
                <label>Minimum level<input placeholder="WARN" value={draft.minLevel} onChange={(event) => updateDraft('minLevel', event.target.value)} /></label>
                <label>From line<input type="number" min="0" value={draft.lineFrom} onChange={(event) => updateDraft('lineFrom', event.target.value)} /></label>
                <label>Through line<input type="number" min="0" value={draft.lineTo} onChange={(event) => updateDraft('lineTo', event.target.value)} /></label>
                <label>Since<input type="datetime-local" value={draft.since} onChange={(event) => updateDraft('since', event.target.value)} /></label>
                <label>Until<input type="datetime-local" value={draft.until} onChange={(event) => updateDraft('until', event.target.value)} /></label>
                <label>Exclude types<input placeholder="REC, SOFTW" value={draft.excludeTypes} onChange={(event) => updateDraft('excludeTypes', event.target.value)} /></label>
                <label className="log-record-toggle"><input type="checkbox" checked={draft.includeRecords} onChange={(event) => updateDraft('includeRecords', event.target.checked)} />Include REC records</label>
              </div>
              <div className="log-filter-actions">
                <button type="button" className="primary-action" onClick={applyFilters}><Filter size={15} aria-hidden="true" />Apply</button>
                <button type="button" className="icon-action" onClick={clearFilters} title="Clear log filters" aria-label="Clear log filters"><RotateCcw size={16} aria-hidden="true" /></button>
              </div>
            </div>
          </details>
        </aside>}

        <section className="panel log-entries-panel" aria-label="Log records">
          <div className="panel-heading log-record-heading">
            <div><p className="eyebrow">{archive}</p><h2>{follow && archive === 'current' ? 'Following latest records' : 'Buffered records'}</h2></div>
            <div className="log-record-actions">
              {selectedEvent && <button type="button" className="quiet-action log-clear-event" onClick={clearSelectedEvent}><X size={15} aria-hidden="true" />Clear event</button>}
              <span className="log-buffer-state">{rows.length.toLocaleString()} rows · {Math.min(MAX_BUFFERED_PAGES, browser.pages.length)} pages</span>
            </div>
          </div>
          {browser.error && <p className="inline-notice">{browser.error.message}</p>}
          <LogRecordTable browser={browser} onSelectEntry={setSelectedEntry} onScroll={handleScroll} events={events.data?.items} selectedEventId={selectedEvent?.event_id} />
        </section>

        {showEvents && <aside className="panel log-events-panel" aria-label="Indexed events">
          <div className="panel-heading"><div><p className="eyebrow">Events</p><h2>Markers</h2></div><ListTree size={17} aria-hidden="true" /></div>
          {events.error && <p className="inline-notice">{events.error.message}</p>}
          <div className="log-event-list">
            {events.data?.items.map((event) => (
              <button type="button" key={event.event_id} onClick={() => selectEvent(event)}>
                <span className="log-event-range">{eventRange(event.start_line, event.end_line)}</span>
                <strong>{event.e_type} · {event.level}</strong>
                <small>{event.message || event.event_id}</small>
              </button>
            ))}
            {events.isLoading && <span className="muted">Loading events…</span>}
            {events.data?.items.length === 0 && <span className="muted">No indexed events in this archive.</span>}
          </div>
        </aside>}
      </section>

      <Modal opened={selectedEntry !== null} onClose={() => setSelectedEntry(null)} title={selectedEntry ? `Raw record ${selectedEntry.line.toLocaleString()}` : 'Raw record'} size="xl">
        {selectedEntry && <>
          <pre className="log-raw-record">{JSON.stringify(selectedEntry.record, null, 2)}</pre>
          {selectedEntry.origin_uuid && <div className="log-detail-actions"><button type="button" className="primary-action" onClick={() => filterByOriginUuid(selectedEntry.origin_uuid!)}><Filter size={15} aria-hidden="true" />Filter by UUID</button></div>}
        </>}
      </Modal>
    </div>
  )
}