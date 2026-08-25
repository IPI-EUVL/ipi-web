import { CircleCheck, CircleHelp, OctagonX, TriangleAlert } from 'lucide-react'

import type { HealthState } from '../api/types'

const icons = {
  ok: CircleCheck,
  warning: TriangleAlert,
  error: OctagonX,
  unknown: CircleHelp,
}

export function StatusGlyph({ state, size = 18 }: { state: HealthState; size?: number }) {
  const Icon = icons[state]
  return <Icon className={`status-icon status-${state}`} size={size} aria-hidden="true" />
}

export function StateLabel({ state, label }: { state: HealthState; label: string }) {
  return (
    <span className={`state-label state-${state}`}>
      <StatusGlyph state={state} size={14} />
      {label}
    </span>
  )
}