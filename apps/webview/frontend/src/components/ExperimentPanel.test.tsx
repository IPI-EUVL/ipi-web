import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { makeLiveSnapshot } from '../test/fixtures'
import { ExperimentPanel } from './ExperimentPanel'

describe('ExperimentPanel', () => {
  afterEach(cleanup)

  it('keeps transition status present and collapsed when no transition is active', () => {
    render(<ExperimentPanel snapshot={makeLiveSnapshot()} />)

    const disclosure = screen.getByText('Transition status').closest('details')
    expect(disclosure).toBeInTheDocument()
    expect(disclosure).not.toHaveAttribute('open')
    expect(screen.getByText('No active transition')).toBeInTheDocument()
  })

  it('summarizes active transition reasons and expands them on demand', () => {
    const snapshot = makeLiveSnapshot()
    snapshot.experiment.reasons = [{ subsystem: 'Target Controller', status: 'Waiting', reason: 'Moving to sample position.' }]

    render(<ExperimentPanel snapshot={snapshot} />)

    const disclosure = screen.getByText('Transition status').closest('details')
    expect(disclosure).not.toHaveAttribute('open')
    expect(screen.getByText('1 subsystem update')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Transition status'))
    expect(disclosure).toHaveAttribute('open')
    expect(screen.getByText('Target Controller')).toBeInTheDocument()
    expect(screen.getByText('Moving to sample position.')).toBeInTheDocument()
  })
})