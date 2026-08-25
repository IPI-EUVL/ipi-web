import { AlertTriangle, ArrowLeft, Clock3, Download, FileBarChart2, Files, Gauge, ListTree, Settings2, ScrollTextIcon } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'wouter'

import { type ExperimentDetail, type GraphAnnotationCategory, useExperiment, useExposureEvents } from '../api/experiments'
import { ExperimentOverview } from '../components/ExperimentOverview'
import { ExperimentLoadingPanel } from '../components/ExperimentLoadingPanel'
import { WaveformWorkspace } from '../components/WaveformWorkspace'
import { ExposureLogView } from './LogsPage'

type DetailTab = 'settings' | 'tags' | 'resources' | 'metrics' | 'waveforms' | 'events' | 'logs'

const tabs: { id: DetailTab; label: string; icon: typeof Gauge }[] = [
  { id: 'settings', label: 'Exposure Settings', icon: Settings2 },
  { id: 'tags', label: 'Record Tags', icon: ListTree },
  { id: 'resources', label: 'Resources', icon: Files },
  { id: 'metrics', label: 'Development Ellipsometry Metrics', icon: FileBarChart2 },
  { id: 'waveforms', label: 'Snapshots', icon: FileBarChart2 },
  { id: 'events', label: 'Events', icon: Clock3 },
  { id: 'logs', label: 'Logs', icon: ScrollTextIcon },
]

function format(value: unknown): string {
  return typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 5 }) : String(value ?? '—')
}

function KeyValues({ values }: { values: Record<string, unknown> }) {
  const entries = Object.entries(values)
  if (!entries.length) return <p className="muted">No indexed values are available.</p>
  return <dl className="experiment-kv">{entries.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{format(value)}</dd></div>)}</dl>
}

function ResourceList({ detail, runId }: { detail: ExperimentDetail; runId: string }) {
  return <div className="resource-list">{detail.resources.map((resource) => (
    <div key={resource.name} className={resource.available ? '' : 'is-unavailable'}>
      <span>
        <strong>{resource.name}</strong>
        <small>
          {resource.resource_type} · {resource.size_bytes === null ? 'size unavailable' : `${resource.size_bytes.toLocaleString()} bytes`}
          {!resource.available && ' · unavailable'}
        </small>
        {resource.error && <small className="resource-error">{resource.error}</small>}
      </span>
      {resource.downloadable ? (
        <a href={`/api/v1/experiments/${runId}/resources/${encodeURIComponent(resource.name)}`} aria-label={`Download ${resource.name}`}>
          <Download size={16} aria-hidden="true" />
        </a>
      ) : (
        <span className="resource-unavailable" aria-label={`${resource.name} is unavailable`} title={resource.error ?? undefined}>
          <AlertTriangle size={16} aria-hidden="true" />
        </span>
      )}
    </div>
  ))}</div>
}

function EventTimeline({ runId }: { runId: string }) {
  const query = useExposureEvents(runId)
  const [source, setSource] = useState('')
  const [categories, setCategories] = useState<Set<GraphAnnotationCategory>>(
    () => new Set(['lifecycle', 'triggers', 'transmitting']),
  )
  const toggleCategory = (category: GraphAnnotationCategory) => setCategories((current) => {
    const next = new Set(current)
    if (next.has(category)) next.delete(category)
    else next.add(category)
    return next
  })
  if (query.isLoading) return <ExperimentLoadingPanel title="Loading exposure events" detail="Reading the recorded timeline." />
  if (query.error || !query.data) return <p className="inline-notice">{query.error?.message ?? 'Event timeline is unavailable.'}</p>
  const timeline = query.data
  const events = timeline.events.filter((event) => {
    const category: GraphAnnotationCategory | null = event.kind === 'lifecycle.phase' ? 'lifecycle' : event.kind === 'timing.triggers_enabled' ? 'triggers' : event.kind === 'timing.euv_transmitting' ? 'transmitting' : null
    return (category === null || categories.has(category)) && (!source || event.stream_name.toLocaleLowerCase().includes(source.toLocaleLowerCase()))
  })
  return <div className="event-timeline"><div className="event-timeline-toolbar"><label>Source<input value={source} onChange={(event) => setSource(event.target.value)} placeholder="Filter source" /></label><div className="annotation-filters" aria-label="Event categories">{(['lifecycle', 'triggers', 'transmitting'] as const).map((category) => <label key={category}><input type="checkbox" checked={categories.has(category)} onChange={() => toggleCategory(category)} />{category === 'lifecycle' ? 'Lifecycle' : category === 'triggers' ? 'Triggers' : 'EUV'}</label>)}</div></div>{!timeline.complete && <p className="inline-notice">Timeline integrity warning: {timeline.issues.join(' ')}</p>}{timeline.complete && timeline.issues.length > 0 && <p className="inline-notice">{timeline.issues.join(' ')}</p>}{events.length === 0 ? <p className="muted">No recorded events match the active filters.</p> : <div className="table-scroll"><table className="data-table event-table"><thead><tr><th>Time</th><th>Source</th><th>Event</th><th>Value</th><th>Correlation</th></tr></thead><tbody>{events.map((event) => <tr key={event.event_id}><td className="numeric-cell">{(event.producer_unix_ns / 1e9).toLocaleString(undefined, { maximumFractionDigits: 6 })}</td><td>{event.stream_name}</td><td>{event.kind}</td><td>{event.kind === 'lifecycle.phase' ? String(event.payload.phase ?? '—') : String(event.payload.value ?? '—')}</td><td>{event.next_sequence === null ? '—' : `next pulse ${event.next_sequence}`}</td></tr>)}</tbody></table></div>}</div>
}

function DetailContent({ detail, tab, runId }: { detail: ExperimentDetail; tab: DetailTab; runId: string }) {
  if (tab === 'settings') return <KeyValues values={detail.settings} />
  if (tab === 'tags') return <KeyValues values={detail.tags} />
  if (tab === 'resources') return <ResourceList detail={detail} runId={runId} />
  if (tab === 'metrics') return detail.metrics.degraded ? <p className="inline-notice">{detail.metrics.error}</p> : <><div className="metric-summary"><span><small>Exposed average</small><strong>{format(detail.metrics.exposed_average_nm)} nm</strong></span><span><small>Blank average</small><strong>{format(detail.metrics.blank_average_nm)} nm</strong></span><span><small>Development</small><strong>{format(detail.metrics.percent_development)}%</strong></span></div><div className="table-scroll"><table className="data-table"><thead><tr><th>Spot</th><th>Thickness (nm)</th><th>GoF</th></tr></thead><tbody>{detail.metrics.measurements.map((measurement, index) => <tr key={index}><td>{measurement.spot_type}</td><td className="numeric-cell">{format(measurement.thickness_nm)}</td><td className="numeric-cell">{format(measurement.goodness_of_fit)}</td></tr>)}</tbody></table></div></>
  if (tab === 'waveforms') return <WaveformWorkspace detail={detail} runId={runId} />
  if (tab === 'events') return <EventTimeline runId={runId} />
  if (tab === 'logs') {
    return <ExposureLogView eventId={detail.log_range.event_id} createdAt={detail.log_range.created_at} endedAt={detail.log_range.ended_at} />
  }
  return null
}

export function ExperimentDetailPage({ runId }: { runId: string }) {
  const [tab, setTab] = useState<DetailTab>('settings')
  const query = useExperiment(runId)
  const backHref = `/experiments${window.location.search}`
  if (query.isLoading) return <div className="page page-enter"><Link className="back-link" href={backHref}><ArrowLeft size={15} aria-hidden="true" />Exposures</Link><ExperimentLoadingPanel detail="Loading data..." /></div>
  if (query.error || !query.data) return <p className="inline-notice">{query.error?.message ?? 'Exposure not found.'}</p>
  const detail = query.data
  return <div className="page page-enter"><section className="page-heading"><div><Link className="back-link" href={backHref}><ArrowLeft size={15} aria-hidden="true" />Exposures</Link><p className="eyebrow">Run {detail.summary.run_id.slice(-8)}</p><h1>{detail.summary.name || 'Untitled experiment'}</h1></div><div className="detail-heading-actions"><span className="run-status has-status">{detail.summary.status ?? 'Unknown'}</span><a className="primary-action" href={`/api/v1/experiments/${runId}/export`}><Download size={15} aria-hidden="true" />Download ZIP</a></div></section><section className="panel overview-panel"><div className="panel-heading"><div><p className="eyebrow">Details</p><h2>Overview</h2></div></div><div className="overview-panel-content"><ExperimentOverview detail={detail} /></div></section><section className="panel">{query.isFetching && <div className="table-refresh-marquee" aria-label="Refreshing experiment data"><span /></div>}{detail.issues.length > 0 && <div className="detail-issues" role="status">{detail.issues.map((issue, index) => <span key={`${issue.section}-${issue.resource_name}-${index}`}><AlertTriangle size={14} aria-hidden="true" />{issue.message}</span>)}</div>}<nav className="detail-tabs" aria-label="Exposure detail sections">{tabs.map(({ id, label, icon: Icon }) => <button type="button" key={id} className={tab === id ? 'is-active' : ''} onClick={() => setTab(id)}><Icon size={15} aria-hidden="true" />{label}</button>)}</nav><div className="detail-tab-content"><DetailContent detail={detail} tab={tab} runId={runId} /></div></section></div>
}