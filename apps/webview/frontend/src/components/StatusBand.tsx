import { Boxes, Clock3, FlaskConical, Layers3 } from 'lucide-react'

import { batchCounts, formatTimestamp, phaseLabel, sourceStateLabel } from '../api/selectors'
import type { LiveConnectionState, LiveResponse } from '../api/types'
import { StatusGlyph } from './StatusGlyph'

export function StatusBand({ snapshot, connectionState }: { snapshot: LiveResponse; connectionState: LiveConnectionState }) {
  const counts = batchCounts(snapshot)
  const connectionLabel = connectionState === 'live' ? 'Streaming' : connectionState === 'reconnecting' ? 'Reconnecting' : connectionState === 'connecting' ? 'Connecting' : 'Offline'

  return (
    <section className={`status-band system-${snapshot.system.state}`} aria-labelledby="system-status-heading">
      <div className="status-primary">
        <StatusGlyph state={snapshot.system.state} size={26} />
        <div>
          <p className="eyebrow" id="system-status-heading">System status</p>
          <strong>{snapshot.system.label}</strong>
        </div>
      </div>
      <div className="status-metric">
        <FlaskConical size={16} aria-hidden="true" />
        <span><small>Phase</small>{phaseLabel(snapshot.experiment.phase)}</span>
      </div>
      <div className="status-metric">
        <Layers3 size={16} aria-hidden="true" />
        <span><small>Batch</small>{snapshot.batch.name || 'No batch'}</span>
      </div>
      <div className="status-metric">
        <Boxes size={16} aria-hidden="true" />
        <span><small>Finished / total</small>{counts.finished} / {counts.total}</span>
      </div>
      <div className="status-metric">
        <Clock3 size={16} aria-hidden="true" />
        <span><small>{connectionLabel}</small>{formatTimestamp(snapshot.generated_at)}</span>
      </div>
      {snapshot.system.issues.length > 0 && (
        <div className="issue-strip" aria-label="Active system issues">
          {snapshot.system.issues.map((issue, index) => (
            <span key={`${issue.source}-${issue.message}-${index}`} className={`issue issue-${issue.severity}`}>
              <strong>{issue.source}</strong>
              {issue.message}
            </span>
          ))}
        </div>
      )}
      <div className="source-strip" aria-label="Data source freshness" tabIndex={0}>
        {Object.entries(snapshot.sources).map(([name, source]) => (
          <span key={name} className={`source-state source-${source.state}`} title={source.error ?? undefined}>
            <span className="source-dot" aria-hidden="true" />
            <span>{name.replace('_', ' ')}</span>
            <small>{sourceStateLabel(source.state)}</small>
          </span>
        ))}
      </div>
    </section>
  )
}