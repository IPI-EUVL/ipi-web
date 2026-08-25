import { Gauge, Timer } from 'lucide-react'

import { progressText } from '../api/selectors'
import type { ProgressSummary } from '../api/types'

export function ProgressDisplay({ progress }: { progress: ProgressSummary }) {
  const percent = progress.percent ?? 0
  const isIndeterminate = progress.mode === 'indeterminate'
  const Icon = progress.mode === 'time' ? Timer : Gauge

  return (
    <div className={`progress-display progress-mode-${progress.mode}`}>
      <div className="progress-heading">
        <span className="progress-icon"><Icon size={18} aria-hidden="true" /></span>
        <div>
          <p className="eyebrow">Exposure progress</p>
          <strong>{progressText(progress)}</strong>
        </div>
        {progress.percent !== null && progress.percent !== undefined && (
          <span className="progress-percent">{Math.round(progress.percent)}%</span>
        )}
      </div>
      <div
        className="progress-track"
        role="progressbar"
        aria-label="Exposure progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={isIndeterminate || progress.mode === 'none' ? undefined : percent}
      >
        {progress.mode !== 'none' && (
          <span
            className={`progress-fill${isIndeterminate ? ' is-indeterminate' : ''}`}
            style={isIndeterminate ? undefined : { width: `${percent}%` }}
          />
        )}
      </div>
    </div>
  )
}