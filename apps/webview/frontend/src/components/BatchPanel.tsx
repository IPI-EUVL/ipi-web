import { CirclePause, ListChecks, ShieldCheck, TriangleAlert } from 'lucide-react'

import { batchCounts, formatNumber, formatTimestamp } from '../api/selectors'
import type { BatchExposure, LiveResponse } from '../api/types'
import { ExposureStateLabel } from './ExposureStateLabel'

function targetText(exposure: BatchExposure): string {
  if (exposure.target_dose !== null && exposure.target_dose > 0) return `${formatNumber(exposure.target_dose)} mJ/cm2`
  if (exposure.target_time !== null && exposure.target_time > 0) return `${formatNumber(exposure.target_time)} s`
  return 'No target'
}

function actualText(exposure: BatchExposure): string {
  if (exposure.target_dose !== null && exposure.target_dose > 0 && exposure.actual_dose !== null) return `${formatNumber(exposure.actual_dose)} mJ/cm2`
  if (exposure.actual_time !== null) return `${formatNumber(exposure.actual_time)} s`
  if (exposure.actual_dose !== null) return `${formatNumber(exposure.actual_dose)} mJ/cm2`
  return '—'
}

function planTargetText(mode: string, target: number): string {
  if (mode === 'dose') return target === 0 ? 'Control' : `${formatNumber(target)} mJ/cm2`
  if (mode === 'time') return `${formatNumber(target)} s`
  return formatNumber(target)
}

function planActualText(mode: string, value: number | null): string {
  if (value === null) return '—'
  return `${formatNumber(value)} ${mode === 'dose' ? 'mJ/cm2' : 's'}`
}

function planState(state: string): string {
  if (state === 'overshot') return 'overshot'
  if (state === 'within_tolerance') return 'succeeded'
  return 'queued'
}

function phaseTone(phase: string | null | undefined): string {
  if (['error', 'error_paused', 'failure_paused', 'start_error'].includes(phase ?? '')) return 'error'
  if (['paused', 'restart_paused', 'waiting_continue', 'cancelling'].includes(phase ?? '')) return 'warning'
  if (phase === 'completed') return 'success'
  if (['starting', 'wait_active', 'wait_controller', 'wait_finalization', 'repair_metrics'].includes(phase ?? '')) return 'active'
  return 'neutral'
}

export function BatchPanel({ snapshot }: { snapshot: LiveResponse }) {
  const counts = batchCounts(snapshot)
  const batch = snapshot.batch
  const exposures = batch.exposures
  const sourceLabel = batch.authoritative ? 'Controller' : 'Inferred history / queue'
  const controllerMessage = batch.controller_message || batch.decision_message
  const decisionMessage = batch.decision_message && batch.decision_message !== controllerMessage
    ? batch.decision_message
    : null
  const controllerTone = phaseTone(batch.controller_phase)

  return (
    <section className="panel batch-panel" aria-labelledby="batch-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Batch</p>
          <h2 id="batch-heading">{batch.name || (batch.authoritative ? 'No active batch' : 'No batch selected')}</h2>
          <p className="batch-source">Source: {sourceLabel}</p>
        </div>
        <div className="batch-summary" aria-label="Batch counts">
          <span><strong>{counts.finished}</strong> finished</span>
          <span><strong>{counts.active}</strong> active</span>
          <span><strong>{counts.queued}</strong> queued</span>
        </div>
      </div>

      {batch.authoritative && (
        <div className="batch-controller-status" aria-label="Batch Controller status">
          <span className={`batch-phase batch-phase-${controllerTone}`}>{batch.controller_phase?.replaceAll('_', ' ') || 'unknown'}</span>
          {batch.execution_mode && <span>{batch.execution_mode}</span>}
          {batch.revision !== null && batch.revision !== undefined && <span>Revision {batch.revision}</span>}
          {batch.lease_owned && <span><ShieldCheck size={14} aria-hidden="true" />Automation lease held</span>}
          {batch.paused && <span><CirclePause size={14} aria-hidden="true" />Paused</span>}
          {batch.cancel_pending && <span>Cancellation pending</span>}
        </div>
      )}

      {batch.authoritative && controllerMessage && (
        <p className={`batch-decision batch-decision-${controllerTone}`}>{controllerMessage}</p>
      )}

      {batch.authoritative && decisionMessage && (
        <p className="batch-next-decision">{decisionMessage}</p>
      )}

      {batch.possibly_truncated && (
        <p className="inline-notice"><TriangleAlert size={15} aria-hidden="true" />Older matching attempts may not be shown.</p>
      )}

      {batch.authoritative && batch.plan_entries.length > 0 && (
        <div className="table-scroll" tabIndex={0}>
          <table className="data-table batch-table batch-plan-table" aria-label="Batch plan progress">
            <thead>
              <tr><th>Order</th><th>Sample</th><th>Target</th><th>Actual</th><th>Remaining</th><th>State</th></tr>
            </thead>
            <tbody>
              {batch.plan_entries.map((entry) => (
                <tr key={`${entry.order}-${entry.sample_number}`}>
                  <td className="numeric-cell">{entry.order}</td>
                  <td>Sample {entry.sample_number}</td>
                  <td className="numeric-cell">{planTargetText(entry.mode, entry.target)}</td>
                  <td className="numeric-cell">{planActualText(entry.mode, entry.cumulative_actual)}</td>
                  <td className="numeric-cell">{entry.overshoot > 0 ? `+${planActualText(entry.mode, entry.overshoot)}` : planActualText(entry.mode, entry.remainder)}</td>
                  <td><ExposureStateLabel state={planState(entry.state)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {exposures.length === 0 ? (
        <div className="panel-empty"><ListChecks size={20} aria-hidden="true" />{batch.authoritative ? 'No exposure attempts recorded for this batch.' : 'No matching exposure attempts.'}</div>
      ) : (
        <div className="table-scroll" tabIndex={0}>
          <table className="data-table batch-table" aria-label="Batch exposure attempts">
            <thead>
              <tr><th>State</th><th>Sample</th><th>Target</th><th>Actual</th><th>Started / queue</th><th>Result</th></tr>
            </thead>
            <tbody>
              {exposures.map((exposure, index) => (
                <tr key={exposure.run_id ?? `queue-${exposure.queue_position}-${index}`}>
                  <td><ExposureStateLabel state={exposure.state} /></td>
                  <td>{exposure.sample_number ? `Sample ${exposure.sample_number}` : 'Unplaced'}</td>
                  <td className="numeric-cell">{targetText(exposure)}</td>
                  <td className="numeric-cell">{actualText(exposure)}</td>
                  <td>{exposure.created_at ? formatTimestamp(exposure.created_at) : exposure.queue_position ? `Queue ${exposure.queue_position}` : '—'}</td>
                  <td className="result-cell">{exposure.end_reason || exposure.status || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {batch.unplaced_exposures.length > 0 && (
        <div className="unplaced-list">
          <strong>Unplaced attempts</strong>
          {batch.unplaced_exposures.map((exposure, index) => (
            <span key={exposure.run_id ?? `unplaced-${index}`}><ExposureStateLabel state={exposure.state} />{exposure.name}</span>
          ))}
        </div>
      )}
    </section>
  )
}