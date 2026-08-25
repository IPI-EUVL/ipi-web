import axe from 'axe-core'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { makeLiveSnapshot } from '../test/fixtures'
import { SampleStage } from './SampleStage'

describe('SampleStage', () => {
  it('renders all positions and supports keyboard selection', async () => {
    const snapshot = makeLiveSnapshot()
    snapshot.batch.exposures = [
      { run_id: null, queue_position: 1, created_at: null, name: 'Batch', sample_number: 2, target_dose: 5, target_time: 0, actual_dose: null, actual_time: null, state: 'queued', status: null, end_reason: null },
      { run_id: '3', queue_position: null, created_at: 1, name: 'Batch', sample_number: 3, target_dose: 5, target_time: 0, actual_dose: 4, actual_time: 1, state: 'succeeded', status: 'STOPPED', end_reason: 'Completed' },
    ]
    snapshot.batch.slots = [
      { sample_number: 2, attempt_count: 1, first_target_dose: 5, first_target_time: 0, cumulative_actual_dose: 0, cumulative_actual_time: 0, state: 'queued', abort_reasons: [] },
      { sample_number: 3, attempt_count: 1, first_target_dose: 5, first_target_time: 0, cumulative_actual_dose: 4, cumulative_actual_time: 1, state: 'succeeded', abort_reasons: [] },
    ]
    const user = userEvent.setup()
    const { container } = render(<SampleStage snapshot={snapshot} />)

    expect(screen.getAllByRole('button')).toHaveLength(12)
    const sampleTwo = screen.getByRole('button', { name: 'Sample 2, queued' })
    sampleTwo.focus()
    await user.keyboard('{Enter}')

    expect(sampleTwo).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('5 mJ/cm2')).toBeInTheDocument()
    expect(screen.getByText('DOOR')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sample 3, succeeded, target not met' })).toHaveClass('is-target-missed')
    expect(screen.getByRole('button', { name: 'Sample 6, unknown' })).toHaveAttribute('transform', 'translate(52 20)')
    const results = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })
    expect(results.violations).toEqual([])
  })
})