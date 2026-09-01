import { Activity, ChevronLeft, ChevronRight, Download, RadioTower, Zap } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
  type ExperimentDetail,
  type GraphAnnotationCategory,
  type ObserverDoseComparison,
  type RunTimeMode,
  type SnapshotGraphSeries,
  type SnapshotSeriesKind,
  type SnapshotTimeMode,
  useObserverDoseComparison,
  useRunDoseSeries,
  useSnapshotAnalysis,
  useSnapshotSeries,
} from '../api/experiments'
import { DoseComparisonChart } from './DoseComparisonChart'
import type { DoseComparisonLine } from './doseComparisonSeries'
import { ExperimentLoadingPanel } from './ExperimentLoadingPanel'
import { SnapshotChart } from './SnapshotChart'

const modes: { value: SnapshotSeriesKind; label: string; icon: typeof Activity }[] = [
  { value: 'voltage', label: 'Voltage', icon: Activity },
  { value: 'peaks', label: 'Peaks', icon: RadioTower },
  { value: 'dose', label: 'Dose / pulse', icon: Zap },
]

const rollingWindows = [1, 10, 50, 100]

function format(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: 6 })
}

type ObserverSeries = ObserverDoseComparison['series'][number]

function observerSourceKey(series: ObserverSeries): string {
  return JSON.stringify([series.source_kind, series.source_id, series.session_id])
}

function algorithmLabel(algorithm: ObserverSeries['algorithm']): string {
  return algorithm === 'captured' ? 'Captured' : 'Legacy compensated'
}

function deltaLabel(value: number, canonical: number | null): string {
  if (canonical === null) return 'Canonical total unavailable'
  const delta = value - canonical
  const sign = delta > 0 ? '+' : ''
  if (canonical === 0) return `${sign}${format(delta)} mJ/cm²`
  return `${sign}${format(delta)} mJ/cm² (${sign}${format(delta / canonical * 100)}%)`
}

type TimedSnapshot = {
  snapshot: ExperimentDetail['snapshots'][number]
}

export function orderSnapshotsByElapsed(snapshots: ExperimentDetail['snapshots']): TimedSnapshot[] {
  return [...snapshots]
    .sort(
      (left, right) => (left.final_sequence ?? Number.POSITIVE_INFINITY) - (right.final_sequence ?? Number.POSITIVE_INFINITY)
        || left.snapshot_id.localeCompare(right.snapshot_id),
    )
    .map((snapshot) => ({ snapshot }))
}

function snapshotTimingLabel(finalSequence: number | null): string {
  return finalSequence === null ? 'capture order unavailable' : `through pulse ${finalSequence.toLocaleString()}`
}

export function WaveformWorkspace({ detail, runId }: { detail: ExperimentDetail; runId: string }) {
  const [selectedSnapshot, setSelectedSnapshot] = useState<string | null>(null)
  const [mode, setMode] = useState<SnapshotSeriesKind>('voltage')
  const [rollingWindow, setRollingWindow] = useState(50)
  const [timeMode, setTimeMode] = useState<SnapshotTimeMode>('wall')
  const [runTimeMode, setRunTimeMode] = useState<RunTimeMode>('runtime')
  const [interSnapshotMode, setInterSnapshotMode] = useState<'cumulative' | 'rate'>('cumulative')
  const [selectedObserverSource, setSelectedObserverSource] = useState<string | null>(null)
  const [visibleObserverAlgorithms, setVisibleObserverAlgorithms] = useState<Set<ObserverSeries['algorithm']>>(
    () => new Set(['captured', 'legacy_compensated']),
  )
  const [visibleCategories, setVisibleCategories] = useState<Set<GraphAnnotationCategory>>(
    () => new Set(['lifecycle', 'triggers', 'transmitting']),
  )
  const selectedByUserRef = useRef(false)
  const selectedWindow = mode === 'voltage' ? 1 : rollingWindow
  const runSeries = useRunDoseSeries(runId, runTimeMode, 'full')
  const observerComparison = useObserverDoseComparison(runId, 'full')
  const selectedSnapshotResource = detail.snapshots.find(({ snapshot_id }) => snapshot_id === selectedSnapshot) ?? null
  const orderedSnapshots = useMemo(
    () => orderSnapshotsByElapsed(detail.snapshots),
    [detail.snapshots],
  )
  const availableSnapshots = useMemo(
    () => orderedSnapshots.filter(({ snapshot }) => snapshot.waveform.available),
    [orderedSnapshots],
  )
  const selectionOrderKey = availableSnapshots.map(({ snapshot }) => snapshot.snapshot_id).join('|')
  const observerSources = useMemo(() => {
    const values = new Map<string, ObserverSeries>()
    for (const item of observerComparison.data?.series ?? []) values.set(observerSourceKey(item), item)
    return [...values.entries()]
  }, [observerComparison.data?.series])

  useEffect(() => {
    selectedByUserRef.current = false
  }, [runId])

  useEffect(() => {
    const firstAvailableSnapshot = availableSnapshots[0]?.snapshot.snapshot_id ?? null
    setSelectedSnapshot((current) => {
      const currentIsAvailable = current !== null && availableSnapshots.some(({ snapshot }) => snapshot.snapshot_id === current)
      return selectedByUserRef.current && currentIsAvailable ? current : firstAvailableSnapshot
    })
  }, [availableSnapshots, runId, selectionOrderKey])

  useEffect(() => {
    setSelectedObserverSource((current) => (
      current !== null && observerSources.some(([key]) => key === current)
        ? current
        : observerSources[0]?.[0] ?? null
    ))
  }, [observerSources, runId])

  const selectSnapshot = (snapshotId: string | null) => {
    selectedByUserRef.current = true
    setSelectedSnapshot(snapshotId)
  }
  const selectedSnapshotIndex = availableSnapshots.findIndex(({ snapshot }) => snapshot.snapshot_id === selectedSnapshot)
  const selectAdjacentSnapshot = (offset: number) => {
    const adjacent = availableSnapshots[selectedSnapshotIndex + offset]?.snapshot.snapshot_id
    if (adjacent) selectSnapshot(adjacent)
  }

  const analysis = useSnapshotAnalysis(runId, selectedSnapshot)
  const series = useSnapshotSeries(runId, selectedSnapshot, mode, selectedWindow, timeMode)
  const interSnapshotSeries = useMemo<SnapshotGraphSeries>(() => {
    const points = runSeries.data?.points ?? []
    return {
      schema_version: '2',
      snapshot_id: runId,
      series: 'dose',
      x_label: runTimeMode === 'runtime' ? 'Transmitting runtime (s)' : 'Wall elapsed time (s)',
      y_label: interSnapshotMode === 'cumulative' ? 'Cumulative dose (mJ/cm²)' : 'Dose rate (mJ/cm²/s)',
      x: points.map((point) => runTimeMode === 'runtime' ? point.runtime_seconds : point.wall_elapsed_seconds),
      y: points.map((point) => interSnapshotMode === 'cumulative' ? point.cumulative_dose_mj_cm2 : point.dose_rate_mj_cm2_s),
      point_count: points.length,
      rolling_window: 1,
      annotations: runSeries.data?.annotations ?? [],
      issues: runSeries.data?.issues ?? [],
    }
  }, [interSnapshotMode, runId, runSeries.data?.annotations, runSeries.data?.issues, runSeries.data?.points, runTimeMode])
  const selectedObserverSeries = useMemo(
    () => (observerComparison.data?.series ?? []).filter((item) => observerSourceKey(item) === selectedObserverSource),
    [observerComparison.data?.series, selectedObserverSource],
  )
  const comparisonLines = useMemo<DoseComparisonLine[]>(() => {
    const lines: DoseComparisonLine[] = []
    const canonicalPoints = runSeries.data?.points ?? []
    if (canonicalPoints.length > 0) {
      lines.push({
        key: 'canonical',
        label: 'Red Pitaya canonical',
        color: '#59c8e8',
        x: canonicalPoints.map((point) => point.wall_elapsed_seconds),
        y: canonicalPoints.map((point) => point.cumulative_dose_mj_cm2),
      })
    }
    for (const item of selectedObserverSeries) {
      if (!visibleObserverAlgorithms.has(item.algorithm)) continue
      lines.push({
        key: `${item.session_id}:${item.algorithm}`,
        label: `Siglent ${algorithmLabel(item.algorithm).toLowerCase()}`,
        color: item.algorithm === 'captured' ? '#e9b85f' : '#ef7d68',
        dashed: item.algorithm === 'legacy_compensated',
        x: item.points.map((point) => point.wall_elapsed_seconds),
        y: item.points.map((point) => point.cumulative_dose_mj_cm2),
      })
    }
    return lines
  }, [runSeries.data?.points, selectedObserverSeries, visibleObserverAlgorithms])
  const canonicalTotal = runSeries.data?.points.at(-1)?.cumulative_dose_mj_cm2 ?? null

  const toggleCategory = (category: GraphAnnotationCategory) => {
    setVisibleCategories((current) => {
      const next = new Set(current)
      if (next.has(category)) next.delete(category)
      else next.add(category)
      return next
    })
  }

  const toggleObserverAlgorithm = (algorithm: ObserverSeries['algorithm']) => {
    setVisibleObserverAlgorithms((current) => {
      const next = new Set(current)
      if (next.has(algorithm)) next.delete(algorithm)
      else next.add(algorithm)
      return next
    })
  }

  if (detail.snapshots.length === 0) return <p className="muted">No complete registered snapshots are available.</p>

  return (
    <div className="waveform-workspace">
      <div className="waveform-toolbar">
        <label>Snapshot
          <select value={selectedSnapshot ?? ''} onChange={(event) => selectSnapshot(event.target.value || null)}>
            <option value="">Select an available registered snapshot</option>
            {orderedSnapshots.map(({ snapshot }) => {
              const available = snapshot.waveform.available
              return <option key={snapshot.snapshot_id} value={snapshot.snapshot_id} disabled={!available}>{snapshot.snapshot_id.slice(-8)} · {snapshotTimingLabel(snapshot.final_sequence)} · {snapshot.waveform.size_bytes === null ? 'size unavailable' : `${snapshot.waveform.size_bytes.toLocaleString()} bytes`}{available ? '' : ' · unavailable'}</option>
            })}
          </select>
        </label>
        <div className="waveform-modes" role="group" aria-label="Waveform graph mode">
          {modes.map(({ value, label, icon: Icon }) => <button type="button" key={value} className={mode === value ? 'is-active' : ''} onClick={() => setMode(value)}><Icon size={15} aria-hidden="true" />{label}</button>)}
        </div>
        {mode !== 'voltage' && <label>Rolling window
          <select value={rollingWindow} onChange={(event) => setRollingWindow(Number(event.target.value))}>
            {rollingWindows.map((window) => <option key={window} value={window}>{window} pulse{window === 1 ? '' : 's'}</option>)}
          </select>
        </label>}
        {mode === 'voltage' && <label>Time scale
          <select value={timeMode} onChange={(event) => setTimeMode(event.target.value as SnapshotTimeMode)}>
            <option value="wall">Wall time</option>
            <option value="apparent">Apparent time</option>
          </select>
        </label>}
        <div className="annotation-filters" aria-label="Graph marker categories">{(['lifecycle', 'triggers', 'transmitting'] as const).map((category) => <label key={category}><input type="checkbox" checked={visibleCategories.has(category)} onChange={() => toggleCategory(category)} />{category === 'lifecycle' ? 'Lifecycle' : category === 'triggers' ? 'Triggers' : 'EUV'}</label>)}</div>
      </div>

      {selectedSnapshot === null && <p className="muted">Select an available snapshot.</p>}
      {series.isLoading && <ExperimentLoadingPanel title="Loading waveform graph" detail="Processing the registered snapshot." />}
      {series.error && <p className="inline-notice">{series.error.message}</p>}
      {series.data && <><div className="waveform-chart-navigation"><button type="button" className="snapshot-edge-button is-previous" onClick={() => selectAdjacentSnapshot(-1)} disabled={selectedSnapshotIndex <= 0} aria-label="Previous snapshot" title="Previous snapshot"><ChevronLeft size={18} aria-hidden="true" /></button><SnapshotChart data={series.data} visibleAnnotationCategories={visibleCategories} /><button type="button" className="snapshot-edge-button is-next" onClick={() => selectAdjacentSnapshot(1)} disabled={selectedSnapshotIndex < 0 || selectedSnapshotIndex >= availableSnapshots.length - 1} aria-label="Next snapshot" title="Next snapshot"><ChevronRight size={18} aria-hidden="true" /></button></div><div className="chart-foot"><span>{series.data.point_count.toLocaleString()} points</span><span>{series.data.x_label}</span><span>{series.data.y_label}</span></div></>}
      {series.data?.issues.length ? <p className="inline-notice">{series.data.issues.join(' ')}</p> : null}

      {analysis.data?.backfill_error && <p className="inline-notice">Analysis succeeded, but snapshot metadata could not be updated: {analysis.data.backfill_error}</p>}
      {analysis.data && <div className="metric-summary"><span><small>Total dose</small><strong>{format(analysis.data.total_dose_mj_cm2)}</strong></span><span><small>Dose rate</small><strong>{format(analysis.data.delivered_dose_rate_mj_cm2_s)}</strong></span><span><small>Effective duration</small><strong>{format(analysis.data.effective_duration_seconds)} s</strong></span><span><small>Exposure runtime</small><strong>{format(analysis.data.runtime_contribution_seconds)} s</strong></span><span><small>Step mode</small><strong>{analysis.data.is_step_exposure ? 'Step' : 'Continuous'} ({analysis.data.step_mode_source})</strong></span></div>}
      {selectedSnapshotResource && <a className="quiet-action waveform-download" href={`/api/v1/experiments/${runId}/resources/${encodeURIComponent(selectedSnapshotResource.waveform.name)}`}><Download size={15} aria-hidden="true" />Download {selectedSnapshotResource.format === 'euv_hdf5' ? 'HDF5' : 'NPZ'}</a>}

      <section className="inter-snapshot-panel">
        <div className="inter-snapshot-heading"><div><p className="eyebrow">Exposure graph</p><h2>Run dose timeline</h2></div><div className="overview-chart-controls"><div className="overview-chart-modes" role="group" aria-label="Run graph time scale"><button type="button" className={runTimeMode === 'runtime' ? 'is-active' : ''} onClick={() => setRunTimeMode('runtime')}>Runtime</button><button type="button" className={runTimeMode === 'wall' ? 'is-active' : ''} onClick={() => setRunTimeMode('wall')}>Wall</button></div><div className="overview-chart-modes" role="group" aria-label="Exposure graph mode"><button type="button" className={interSnapshotMode === 'cumulative' ? 'is-active' : ''} onClick={() => setInterSnapshotMode('cumulative')}>Dose</button><button type="button" className={interSnapshotMode === 'rate' ? 'is-active' : ''} onClick={() => setInterSnapshotMode('rate')}>Rate</button></div></div></div>
        {(runSeries.isLoading || runSeries.data?.status === 'missing' || runSeries.data?.status === 'busy') && <ExperimentLoadingPanel title="Preparing exposure graph" detail="Reading the persisted pulse graph." />}
        {runSeries.data?.status === 'waiting_for_completion' && <ExperimentLoadingPanel title="Exposure graph pending" detail="The graph is created after the active exposure completes." />}
        {interSnapshotSeries.point_count > 0 && <><SnapshotChart data={interSnapshotSeries} visibleAnnotationCategories={visibleCategories} /><div className="chart-foot"><span>{interSnapshotSeries.point_count.toLocaleString()} graph points</span><span>{runSeries.data?.raw_pulse_count.toLocaleString() ?? 0} source pulses</span><span>{interSnapshotSeries.x_label}</span><span>{interSnapshotSeries.y_label}</span></div></>}
        {runSeries.data?.status === 'complete' && interSnapshotSeries.point_count === 0 && <p className="muted">This exposure has no persisted pulse points to plot.</p>}
        {runSeries.data?.status === 'error' && <p className="inline-notice">The persisted exposure graph could not be read.</p>}
        {runSeries.data?.errors.length ? <p className="overview-analysis-errors">{runSeries.data.errors.join(' ')}</p> : null}
        {runSeries.data?.issues.length ? <p className="inline-notice">{runSeries.data.issues.join(' ')}</p> : null}
      </section>

      <section className="inter-snapshot-panel dose-comparison-panel">
        <div className="inter-snapshot-heading">
          <div><p className="eyebrow">Source comparison</p><h2>Canonical and observer dose</h2></div>
          {observerSources.length > 0 && <div className="dose-comparison-controls">
            <label>Observer source
              <select value={selectedObserverSource ?? ''} onChange={(event) => setSelectedObserverSource(event.target.value || null)}>
                {observerSources.map(([key, item]) => (
                  <option key={key} value={key}>{item.source_kind} / {item.source_id} · {item.session_id.slice(-8)}</option>
                ))}
              </select>
            </label>
            <div className="annotation-filters" aria-label="Observer algorithms">
              {(['captured', 'legacy_compensated'] as const).map((algorithm) => (
                <label key={algorithm}>
                  <input type="checkbox" checked={visibleObserverAlgorithms.has(algorithm)} onChange={() => toggleObserverAlgorithm(algorithm)} />
                  {algorithmLabel(algorithm)}
                </label>
              ))}
            </div>
          </div>}
        </div>
        {observerComparison.isLoading && <ExperimentLoadingPanel title="Loading observer comparison" detail="Reading persisted source-qualified products." />}
        {observerComparison.error && <p className="inline-notice">{observerComparison.error.message}</p>}
        {observerComparison.data?.status === 'missing' && <p className="muted">No observer dose products are attached to this exposure.</p>}
        {comparisonLines.length > 0 && observerComparison.data?.status === 'complete' && <DoseComparisonChart lines={comparisonLines} />}
        {observerComparison.data?.status === 'complete' && selectedObserverSeries.length > 0 && (
          <div className="dose-comparison-table-wrap">
            <table className="dose-comparison-table">
              <thead><tr><th>Series</th><th>Total dose</th><th>Delta</th><th>Calibration</th><th>Completeness</th></tr></thead>
              <tbody>
                <tr>
                  <td><strong>Red Pitaya</strong><small>Canonical</small></td>
                  <td>{canonicalTotal === null ? '--' : `${format(canonicalTotal)} mJ/cm²`}</td>
                  <td>Reference</td>
                  <td>Active canonical analysis</td>
                  <td>Authoritative</td>
                </tr>
                {selectedObserverSeries.map((item) => (
                  <tr key={`${item.session_id}:${item.algorithm}`}>
                    <td><strong>{algorithmLabel(item.algorithm)}</strong><small>{item.source_kind} / {item.source_id}</small></td>
                    <td>{format(item.total_dose_mj_cm2)} mJ/cm²</td>
                    <td>{deltaLabel(item.total_dose_mj_cm2, canonicalTotal)}</td>
                    <td>{item.calibration_name} r{item.calibration_revision}<small>{item.calibration_hash.slice(0, 12)}</small></td>
                    <td>{item.completeness.included_snapshot_count}/{item.completeness.snapshot_count} transfers
                      <small className={item.status === 'incomplete' ? 'is-warning' : ''}>
                        {item.status}
                        {item.completeness.unknown_eligibility_snapshot_count > 0 ? ` · ${item.completeness.unknown_eligibility_snapshot_count} timing unknown` : ''}
                        {item.completeness.unknown_step_mode_snapshot_count > 0 ? ` · ${item.completeness.unknown_step_mode_snapshot_count} mode inferred` : ''}
                      </small>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {selectedObserverSeries.flatMap((item) => item.issues).length > 0 && (
          <p className="inline-notice">{selectedObserverSeries.flatMap((item) => item.issues).join(' ')}</p>
        )}
      </section>
    </div>
  )
}