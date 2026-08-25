import { useState } from 'react'

import { type ExperimentDetail, type GraphAnnotationCategory, type RunTimeMode, type SnapshotGraphSeries, useRunDoseSeries } from '../api/experiments'
import { ExperimentLoadingPanel } from './ExperimentLoadingPanel'
import { SnapshotChart } from './SnapshotChart'

function format(value: number | null, unit = ''): string {
  return value === null ? '—' : `${value.toLocaleString(undefined, { maximumFractionDigits: 4 })}${unit}`
}

export function ExperimentOverview({ detail }: { detail: ExperimentDetail }) {
  const { summary, metrics } = detail
  const [seriesMode, setSeriesMode] = useState<'cumulative' | 'rate'>('cumulative')
  const [timeMode, setTimeMode] = useState<RunTimeMode>('runtime')
  const [visibleCategories, setVisibleCategories] = useState<Set<GraphAnnotationCategory>>(
    () => new Set(['lifecycle', 'triggers', 'transmitting']),
  )
  const runSeries = useRunDoseSeries(summary.run_id, timeMode, 'thumbnail')
  const points = runSeries.data?.points ?? []
  const summarySeries: SnapshotGraphSeries = {
    schema_version: '2',
    snapshot_id: summary.run_id,
    series: 'dose',
    x_label: timeMode === 'runtime' ? 'Transmitting runtime (s)' : 'Wall elapsed time (s)',
    y_label: seriesMode === 'cumulative' ? 'Cumulative dose (mJ/cm²)' : 'Dose rate (mJ/cm²/s)',
    x: points.map((point) => timeMode === 'runtime' ? point.runtime_seconds : point.wall_elapsed_seconds),
    y: points.map((point) => seriesMode === 'cumulative' ? point.cumulative_dose_mj_cm2 : point.dose_rate_mj_cm2_s),
    point_count: points.length,
    rolling_window: 1,
    annotations: runSeries.data?.annotations ?? [],
    issues: runSeries.data?.issues ?? [],
  }
  const toggleCategory = (category: GraphAnnotationCategory) => {
    setVisibleCategories((current) => {
      const next = new Set(current)
      if (next.has(category)) next.delete(category)
      else next.add(category)
      return next
    })
  }

  return (
    <div className="overview-focus">
      <div className="overview-primary-metrics">
        <span><small>Delivered dose</small><strong>{format(summary.actual_dose, ' mJ/cm²')}</strong><em>Target {format(summary.target_dose, ' mJ/cm²')}</em></span>
        <span><small>Runtime</small><strong>{format(summary.runtime, ' s')}</strong><em>{format(summary.effective_dose_rate, ' mJ/cm²/s')}</em></span>
        <span><small>Development</small><strong>{format(metrics.percent_development, '%')}</strong><em>Exposed {format(metrics.exposed_average_nm, ' nm')}</em></span>
        <span><small>Blank thickness</small><strong>{format(metrics.blank_average_nm, ' nm')}</strong><em>{summary.status ?? 'Unknown'}</em></span>
      </div>
      <div className="overview-chart-panel">
        <div className="overview-chart-heading"><div><p className="eyebrow">Exposure graph</p><h2>{seriesMode === 'cumulative' ? 'Cumulative dose' : 'Dose rate'}</h2></div><div className="overview-chart-controls"><div className="overview-chart-modes" role="group" aria-label="Overview run graph time scale"><button type="button" className={timeMode === 'runtime' ? 'is-active' : ''} onClick={() => setTimeMode('runtime')}>Runtime</button><button type="button" className={timeMode === 'wall' ? 'is-active' : ''} onClick={() => setTimeMode('wall')}>Wall</button></div><div className="overview-chart-modes" role="group" aria-label="Overview run graph series"><button type="button" className={seriesMode === 'cumulative' ? 'is-active' : ''} onClick={() => setSeriesMode('cumulative')}>Dose</button><button type="button" className={seriesMode === 'rate' ? 'is-active' : ''} onClick={() => setSeriesMode('rate')}>Rate</button></div></div></div>
        {(runSeries.isLoading || runSeries.data?.status === 'missing' || runSeries.data?.status === 'busy') && <ExperimentLoadingPanel title="Preparing exposure graph" detail="Reading the persisted pulse graph." />}
        {runSeries.data?.status === 'waiting_for_completion' && <ExperimentLoadingPanel title="Exposure graph pending" detail="The graph is created after the active exposure completes." />}
        <div className="annotation-filters is-compact" aria-label="Overview marker categories">{(['lifecycle', 'triggers', 'transmitting'] as const).map((category) => <label key={category}><input type="checkbox" checked={visibleCategories.has(category)} onChange={() => toggleCategory(category)} />{category === 'lifecycle' ? 'Lifecycle' : category === 'triggers' ? 'Triggers' : 'EUV'}</label>)}</div>
        {summarySeries.point_count > 0 && <SnapshotChart data={summarySeries} compact visibleAnnotationCategories={visibleCategories} />}
        {runSeries.data?.status === 'complete' && summarySeries.point_count === 0 && <p className="overview-chart-empty">This exposure has no persisted pulse points to plot.</p>}
        {runSeries.data?.status === 'error' && <p className="inline-notice">The persisted exposure graph could not be read.</p>}
        {runSeries.data?.errors.length ? <p className="overview-analysis-errors">{runSeries.data.errors.join(' ')}</p> : null}
        {runSeries.data?.issues.length ? <p className="overview-analysis-errors">{runSeries.data.issues.join(' ')}</p> : null}
      </div>
      <p className="overview-description">{summary.description || 'No description was recorded.'}</p>
    </div>
  )
}