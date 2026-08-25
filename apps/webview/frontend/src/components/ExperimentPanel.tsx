import { ChevronRight, Droplets, Filter, FlaskConical, Gauge, Layers3, UserRound, Wind } from 'lucide-react'

import { formatNumber, phaseLabel } from '../api/selectors'
import type { LiveResponse } from '../api/types'
import { ProgressDisplay } from './ProgressDisplay'

type DetailItemProps = {
  icon: typeof UserRound
  label: string
  value: string | number | null | undefined
}

function DetailItem({ icon: Icon, label, value }: DetailItemProps) {
  if (value === null || value === undefined || value === '') return null
  return (
    <div className="detail-item">
      <Icon size={15} aria-hidden="true" />
      <span><small>{label}</small>{value}</span>
    </div>
  )
}

export function ExperimentPanel({ snapshot }: { snapshot: LiveResponse }) {
  const details = snapshot.experiment.details

  return (
    <section className="panel experiment-panel" aria-labelledby="experiment-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Current exposure</p>
          <h2 id="experiment-heading">{details?.name || phaseLabel(snapshot.experiment.phase)}</h2>
        </div>
        <span className={`phase-label phase-${snapshot.experiment.phase}`}>
          <FlaskConical size={15} aria-hidden="true" />
          {phaseLabel(snapshot.experiment.phase)}
        </span>
      </div>

      {details?.description && <p className="experiment-description">{details.description}</p>}
      <ProgressDisplay progress={snapshot.progress} />

      {details ? (
        <div className="detail-grid">
          <DetailItem icon={UserRound} label="Operator" value={details.operator} />
          <DetailItem icon={Layers3} label="Sample" value={details.sample_number ? `Sample ${details.sample_number}` : null} />
          <DetailItem icon={FlaskConical} label="Sample type" value={details.sample_type} />
          <DetailItem icon={Filter} label="Zr filter" value={details.zr_filter} />
          <DetailItem icon={Gauge} label="Base pressure" value={details.base_pressure === null ? null : formatNumber(details.base_pressure, 3)} />
          <DetailItem icon={Droplets} label="Operating pressure" value={details.operating_pressure === null ? null : formatNumber(details.operating_pressure, 3)} />
          <DetailItem icon={Wind} label="Flow" value={details.flow_sccm === null ? null : `${formatNumber(details.flow_sccm)} sccm`} />
        </div>
      ) : (
        <p className="panel-empty">No exposure is currently active.</p>
      )}

      <details className="transition-status">
        <summary>
          <ChevronRight size={16} aria-hidden="true" />
          <span>
            <strong>Transition status</strong>
            <small>{snapshot.experiment.reasons.length > 0
              ? `${snapshot.experiment.reasons.length} subsystem update${snapshot.experiment.reasons.length === 1 ? '' : 's'}`
              : 'No active transition'}</small>
          </span>
        </summary>
        {snapshot.experiment.reasons.length > 0 ? (
          <div className="reason-list" aria-label="Exposure preparation status">
          {snapshot.experiment.reasons.map((reason, index) => (
            <div className="reason-row" key={`${reason.subsystem}-${index}`}>
              <span>{reason.subsystem}</span>
              <strong>{reason.status}</strong>
              {reason.reason && <small>{reason.reason}</small>}
            </div>
          ))}
          </div>
        ) : <p className="transition-empty">No subsystem status updates are currently reported.</p>}
      </details>
    </section>
  )
}