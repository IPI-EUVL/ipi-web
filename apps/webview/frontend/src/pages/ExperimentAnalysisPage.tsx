import { ArrowLeft, ChartNoAxesCombined, Download } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'wouter'

import { useRunComparisons } from '../api/experiments'
import { ExperimentLoadingPanel } from '../components/ExperimentLoadingPanel'
import { type ComparisonTrace, RunComparisonChart } from '../components/RunComparisonChart'

const traceColors = ['#59c8e8', '#68d391', '#e9b85f', '#ef7b75', '#6ca5f8', '#c5a3ff', '#f29f67', '#8bd3c7']

function selectedRunIds(): string[] {
  const raw = new URLSearchParams(window.location.search).get('run_ids') ?? ''
  return [...new Set(raw.split(',').map((value) => value.trim()).filter(Boolean))]
}

export function ExperimentAnalysisPage() {
  const runIds = selectedRunIds()
  const [mode, setMode] = useState<'cumulative' | 'rate'>('cumulative')
  const [hidden, setHidden] = useState<Set<string>>(() => new Set())
  const comparison = useRunComparisons(runIds)
  const traces: ComparisonTrace[] = runIds.map((runId, index) => {
    const detail = comparison.details[index]?.data
    const series = comparison.series[index]?.data
    return {
      id: runId,
      label: detail?.summary.name || `Run …${runId.slice(-8)}`,
      color: traceColors[index % traceColors.length],
      x: series?.points.map((point) => point.runtime_seconds) ?? [],
      y: series?.points.map((point) => mode === 'cumulative' ? point.cumulative_dose_mj_cm2 : point.dose_rate_mj_cm2_s) ?? [],
      visible: !hidden.has(runId),
    }
  })
  const running = comparison.series.some((query) => query.isLoading || ['missing', 'waiting_for_completion', 'busy'].includes(query.data?.status ?? ''))
  const pointCount = traces.reduce((total, trace) => total + trace.x.length, 0)

  const toggleTrace = (runId: string) => {
    setHidden((current) => {
      const next = new Set(current)
      if (next.has(runId)) next.delete(runId)
      else next.add(runId)
      return next
    })
  }

  const downloadCsv = () => {
    const rows = ['run_id,run_name,elapsed_seconds,value,series']
    traces.forEach((trace) => {
      trace.x.forEach((xValue, index) => {
        const escapedName = `"${trace.label.replaceAll('"', '""')}"`
        rows.push(`${trace.id},${escapedName},${xValue},${trace.y[index]},${mode}`)
      })
    })
    const url = URL.createObjectURL(new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `experiment-${mode}-comparison.csv`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  if (runIds.length < 2) {
    return <div className="page page-enter"><Link className="back-link" href="/experiments"><ArrowLeft size={15} aria-hidden="true" />Exposures</Link><p className="inline-notice">Select at least two experiments to compare.</p></div>
  }

  return (
    <div className="page page-enter">
      <section className="page-heading">
        <div><Link className="back-link" href="/experiments"><ArrowLeft size={15} aria-hidden="true" />Exposures</Link><p className="eyebrow">Cross-run analysis</p><h1>Exposure comparison</h1><p>Each run starts at elapsed time zero and uses its persisted pulse graph.</p></div>
        <button type="button" className="quiet-action" onClick={downloadCsv} disabled={pointCount === 0}><Download size={15} aria-hidden="true" />Download CSV</button>
      </section>
      <section className="panel analysis-panel">
        <div className="analysis-toolbar">
          <div className="analysis-mode" role="group" aria-label="Comparison series">
            <button type="button" className={mode === 'cumulative' ? 'is-active' : ''} onClick={() => setMode('cumulative')}><ChartNoAxesCombined size={15} aria-hidden="true" />Cumulative dose</button>
            <button type="button" className={mode === 'rate' ? 'is-active' : ''} onClick={() => setMode('rate')}><ChartNoAxesCombined size={15} aria-hidden="true" />Dose rate</button>
          </div>
          <span>{pointCount.toLocaleString()} derived points</span>
        </div>
        {running && <ExperimentLoadingPanel title="Loading selected graphs" detail="Waiting for persisted exposure graph artifacts." />}
        {pointCount > 0 && <RunComparisonChart traces={traces} yLabel={mode === 'cumulative' ? 'Cumulative dose (mJ/cm²)' : 'Dose rate (mJ/cm²/s)'} />}
        <div className="analysis-legend" aria-label="Run visibility">
          {traces.map((trace, index) => {
            const status = comparison.series[index]?.data?.status ?? (comparison.series[index]?.isLoading ? 'loading' : 'unavailable')
            const errors = comparison.series[index]?.data?.errors.length ?? 0
            return <label key={trace.id}><input type="checkbox" checked={trace.visible} onChange={() => toggleTrace(trace.id)} /><span className="trace-swatch" style={{ background: trace.color }} /><strong>{trace.label}</strong><small>{status}{errors ? ` · ${errors} errors` : ''}</small></label>
          })}
        </div>
      </section>
    </div>
  )
}