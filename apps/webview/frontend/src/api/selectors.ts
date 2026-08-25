import type {
  BatchExposure,
  BatchSlot,
  LiveResponse,
  ProgressSummary,
  PublicExperimentPhase,
  SourceState,
} from './types'

export type ExposureState = 'current' | 'queued' | 'failed' | 'stopped' | 'overshot' | 'succeeded' | 'unknown'

export type StageSlotView = {
  sampleNumber: number
  state: ExposureState
  attempts: BatchExposure[]
  summary: BatchSlot | null
  isStageCurrent: boolean
  missedTarget: boolean
}

const statePriority: Record<ExposureState, number> = {
  current: 5,
  queued: 4,
  failed: 3,
  stopped: 2,
  overshot: 2,
  succeeded: 1,
  unknown: 0,
}

const phaseLabels: Record<PublicExperimentPhase, string> = {
  checking_system: 'Checking system',
  preparing: 'Preparing',
  initializing: 'Initializing',
  exposing: 'Exposing',
  stopping: 'Stopping',
  idle: 'Idle',
}

export function phaseLabel(phase: PublicExperimentPhase): string {
  return phaseLabels[phase]
}

export function normalizeExposureState(state: string): ExposureState {
  return state in statePriority ? state as ExposureState : 'unknown'
}

function belowTarget(actual: number, target: number): boolean {
  const tolerance = Math.max(Math.abs(target) * 1e-6, 1e-9)
  return actual < target - tolerance
}

export function slotMissedTarget(summary: BatchSlot | null, state: ExposureState): boolean {
  if (!summary || state === 'current' || state === 'queued') return false
  if (summary.first_target_dose !== null && summary.first_target_dose > 0) {
    return belowTarget(summary.cumulative_actual_dose, summary.first_target_dose)
  }
  if (summary.first_target_time !== null && summary.first_target_time > 0) {
    return belowTarget(summary.cumulative_actual_time, summary.first_target_time)
  }
  return false
}

export function deriveStageSlots(snapshot: LiveResponse): StageSlotView[] {
  const attemptsBySample = new Map<number, BatchExposure[]>()
  for (const exposure of snapshot.batch.exposures) {
    if (exposure.sample_number === null || exposure.sample_number === undefined) continue
    const attempts = attemptsBySample.get(exposure.sample_number) ?? []
    attempts.push(exposure)
    attemptsBySample.set(exposure.sample_number, attempts)
  }
  const summaries = new Map(snapshot.batch.slots.map((slot) => [slot.sample_number, slot]))
  return Array.from({ length: 12 }, (_, index) => {
    const sampleNumber = index + 1
    const attempts = attemptsBySample.get(sampleNumber) ?? []
    let state: ExposureState = 'unknown'
    for (const attempt of attempts) {
      const candidate = normalizeExposureState(attempt.state)
      if (statePriority[candidate] > statePriority[state]) state = candidate
    }
    const summary = summaries.get(sampleNumber) ?? null
    const summaryState = summary ? normalizeExposureState(summary.state) : 'unknown'
    if (summaryState === 'succeeded' || summaryState === 'overshot') state = summaryState
    else if (attempts.length === 0 && summary) state = summaryState
    return {
      sampleNumber,
      state,
      attempts,
      summary,
      isStageCurrent: snapshot.stage.current_sample_number === sampleNumber,
      missedTarget: slotMissedTarget(summary, state),
    }
  })
}

export function batchCounts(snapshot: LiveResponse) {
  if (snapshot.batch.authoritative) {
    const planEntries = snapshot.batch.plan_entries
    const finished = planEntries.filter((entry) => ['within_tolerance', 'overshot'].includes(entry.state)).length
    const queued = planEntries.filter((entry) => !['within_tolerance', 'overshot'].includes(entry.state)).length
    const active = snapshot.batch.controller_phase === 'wait_active' || snapshot.batch.controller_phase === 'starting' ? 1 : 0
    return { finished, active, queued, total: planEntries.length }
  }
  const result = { finished: 0, active: 0, queued: 0, total: snapshot.batch.exposures.length }
  for (const exposure of snapshot.batch.exposures) {
    const state = normalizeExposureState(exposure.state)
    if (state === 'succeeded' || state === 'overshot' || state === 'failed') result.finished += 1
    if (state === 'current') result.active += 1
    if (state === 'queued') result.queued += 1
  }
  return result
}

export function progressText(progress: ProgressSummary): string {
  if (progress.mode === 'none') return 'No active exposure'
  if (progress.mode === 'indeterminate') return 'Target not specified'
  const unit = progress.unit ? ` ${progress.unit}` : ''
  const current = progress.current === null ? 'Waiting' : formatNumber(progress.current)
  const target = progress.target === null ? '—' : formatNumber(progress.target)
  return `${current} / ${target}${unit}`
}

export function formatNumber(value: number, maximumFractionDigits = 2): string {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits }).format(value)
}

export function formatTimestamp(timestamp: number | null | undefined): string {
  if (timestamp === null || timestamp === undefined) return 'Never'
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(timestamp * 1000))
}

export function sourceStateLabel(state: SourceState): string {
  const labels: Record<SourceState, string> = {
    available: 'Available',
    not_applicable: 'N/A',
    degraded: 'Degraded',
    stale: 'Stale',
    unavailable: 'Unavailable',
  }
  return labels[state]
}