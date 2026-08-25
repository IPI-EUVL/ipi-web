import { CircleCheck, CircleDot, CircleHelp, CirclePause, Clock3, TriangleAlert, XCircle } from 'lucide-react'

import { normalizeExposureState, type ExposureState } from '../api/selectors'

const stateIcons = {
  current: CircleDot,
  queued: Clock3,
  failed: XCircle,
  stopped: CirclePause,
  overshot: TriangleAlert,
  succeeded: CircleCheck,
  unknown: CircleHelp,
}

const stateLabels: Record<ExposureState, string> = {
  current: 'Current',
  queued: 'Queued',
  failed: 'Failed',
  stopped: 'Stopped',
  overshot: 'Overshot',
  succeeded: 'Succeeded',
  unknown: 'Unknown',
}

export function ExposureStateLabel({ state }: { state: string }) {
  const normalized = normalizeExposureState(state)
  const Icon = stateIcons[normalized]
  return (
    <span className={`exposure-state exposure-${normalized}`}>
      <Icon size={14} aria-hidden="true" />
      {stateLabels[normalized]}
    </span>
  )
}