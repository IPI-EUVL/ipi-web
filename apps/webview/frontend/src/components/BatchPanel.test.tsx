import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { makeLiveSnapshot } from '../test/fixtures'
import { BatchPanel } from './BatchPanel'

describe('BatchPanel', () => {
  afterEach(cleanup)

  it('shows authoritative controller state, ordered plan progress, and attempts', () => {
    const snapshot = makeLiveSnapshot()
    snapshot.batch = {
      ...snapshot.batch,
      authoritative: true,
      batch_id: '11111111-1111-1111-1111-111111111111',
      name: 'Contrast curve',
      controller_phase: 'waiting_continue',
      controller_message: 'Manual mode is ready.',
      execution_mode: 'manual',
      revision: 3,
      lease_owned: true,
      paused: false,
      cancel_pending: false,
      decision_kind: 'start_remainder',
      decision_message: 'Operator Continue is required.',
      plan_entries: [
        { order: 1, sample_number: 5, mode: 'dose', target: 10, cumulative_actual: 5, attempt_count: 1, state: 'under_target', remainder: 5, overshoot: 0 },
        { order: 2, sample_number: 2, mode: 'dose', target: 20, cumulative_actual: 21, attempt_count: 1, state: 'overshot', remainder: 0, overshoot: 1 },
      ],
      exposures: [
        { run_id: '2', queue_position: null, created_at: 1, name: 'Contrast curve', sample_number: 5, target_dose: 10, target_time: 0, actual_dose: 5, actual_time: 2, state: 'stopped', status: 'STOPPED', end_reason: 'done' },
      ],
    }

    render(<BatchPanel snapshot={snapshot} />)

    expect(screen.getByRole('heading', { name: 'Contrast curve' })).toBeInTheDocument()
    expect(screen.getByText('Source: Controller')).toBeInTheDocument()
    expect(screen.getByText('waiting continue')).toBeInTheDocument()
    expect(screen.getByText('Manual mode is ready.')).toBeInTheDocument()
    expect(screen.getByText('Automation lease held')).toBeInTheDocument()
    const planTable = screen.getByRole('table', { name: 'Batch plan progress' })
    expect(planTable).toBeInTheDocument()
    expect(within(planTable).getByText('Sample 5')).toBeInTheDocument()
    expect(within(planTable).getByText('+1 mJ/cm2')).toBeInTheDocument()
    expect(within(planTable).getByText('Overshot')).toBeInTheDocument()
    expect(screen.getByText('Stopped')).toBeInTheDocument()
    expect(screen.getByRole('table', { name: 'Batch exposure attempts' })).toBeInTheDocument()
  })

  it('labels inferred data as fallback when the controller is unavailable', () => {
    const snapshot = makeLiveSnapshot()
    snapshot.batch = {
      ...snapshot.batch,
      name: 'Inferred batch',
      selection_source: 'history',
      exposures: [
        { run_id: '3', queue_position: null, created_at: 1, name: 'Inferred batch', sample_number: 1, target_dose: 5, target_time: 0, actual_dose: 5, actual_time: 2, state: 'succeeded', status: 'STOPPED', end_reason: 'done' },
      ],
    }

    render(<BatchPanel snapshot={snapshot} />)

    expect(screen.getByText('Source: Inferred history / queue')).toBeInTheDocument()
    expect(screen.queryByRole('table', { name: 'Batch plan progress' })).not.toBeInTheDocument()
  })
})