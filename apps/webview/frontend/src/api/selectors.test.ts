import { describe, expect, it } from 'vitest'

import { batchCounts, deriveStageSlots, phaseLabel, progressText, sourceStateLabel } from './selectors'
import { makeLiveSnapshot } from '../test/fixtures'

describe('live selectors', () => {
  it('uses current, queued, failed, succeeded precedence for stage slots', () => {
    const snapshot = makeLiveSnapshot()
    snapshot.batch.exposures = [
      { run_id: '1', queue_position: null, created_at: 1, name: 'Batch', sample_number: 2, target_dose: 5, target_time: 0, actual_dose: 2, actual_time: 1, state: 'failed', status: 'ABORTED', end_reason: 'Fault' },
      { run_id: null, queue_position: 1, created_at: null, name: 'Batch', sample_number: 2, target_dose: 5, target_time: 0, actual_dose: null, actual_time: null, state: 'queued', status: null, end_reason: null },
      { run_id: '2', queue_position: null, created_at: 2, name: 'Batch', sample_number: 3, target_dose: 5, target_time: 0, actual_dose: 1, actual_time: 1, state: 'current', status: null, end_reason: null },
    ]
    snapshot.stage.current_sample_number = 3

    const slots = deriveStageSlots(snapshot)

    expect(slots[1].state).toBe('queued')
    expect(slots[2].state).toBe('current')
    expect(slots[2].isStageCurrent).toBe(true)
    expect(batchCounts(snapshot)).toEqual({ finished: 1, active: 1, queued: 1, total: 3 })
  })

  it('formats phase and progress without inventing missing values', () => {
    expect(phaseLabel('checking_system')).toBe('Checking system')
    expect(progressText({ mode: 'dose', current: 2.345, target: 5, unit: 'mJ/cm2', percent: 46.9 })).toBe('2.35 / 5 mJ/cm2')
    expect(progressText({ mode: 'indeterminate', current: null, target: null, unit: null, percent: null })).toBe('Target not specified')
    expect(sourceStateLabel('not_applicable')).toBe('N/A')
  })

  it('marks completed slots that remain below their active target', () => {
    const snapshot = makeLiveSnapshot()
    snapshot.batch.exposures = [
      { run_id: '4', queue_position: null, created_at: 1, name: 'Batch', sample_number: 4, target_dose: 10, target_time: 0, actual_dose: 9, actual_time: 1, state: 'succeeded', status: 'STOPPED', end_reason: 'Completed' },
      { run_id: '5', queue_position: null, created_at: 2, name: 'Batch', sample_number: 5, target_dose: 10, target_time: 0, actual_dose: 10, actual_time: 1, state: 'succeeded', status: 'STOPPED', end_reason: 'Completed' },
    ]
    snapshot.batch.slots = [
      { sample_number: 4, attempt_count: 1, first_target_dose: 10, first_target_time: 0, cumulative_actual_dose: 9, cumulative_actual_time: 1, state: 'succeeded', abort_reasons: [] },
      { sample_number: 5, attempt_count: 1, first_target_dose: 10, first_target_time: 0, cumulative_actual_dose: 10, cumulative_actual_time: 1, state: 'succeeded', abort_reasons: [] },
    ]

    const slots = deriveStageSlots(snapshot)

    expect(slots[3].missedTarget).toBe(true)
    expect(slots[4].missedTarget).toBe(false)
  })
})