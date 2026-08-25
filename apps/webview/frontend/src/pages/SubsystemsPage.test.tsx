import axe from 'axe-core'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { LiveViewState } from '../App'
import { makeLiveSnapshot } from '../test/fixtures'
import { SubsystemsPage } from './SubsystemsPage'

describe('SubsystemsPage', () => {
  it('shows only the sanitized subsystem contract accessibly', async () => {
    const snapshot = makeLiveSnapshot()
    snapshot.subsystems = [
      { name: 'Exposure Controller', critical: true, connected: true, primary_status: 'Running', issues: [] },
      { name: 'Laser Controller', critical: true, connected: false, primary_status: 'Disconnected', issues: [{ severity: 'error', message: 'Connection lost' }] },
    ]
    snapshot.system = { state: 'error', label: 'Errors reported', issues: [] }
    const live = { snapshot, connectionState: 'live', error: null, isLoading: false, lastEventAt: null } as LiveViewState
    const { container } = render(<SubsystemsPage live={live} />)

    expect(screen.getByRole('heading', { name: 'Subsystems' })).toBeInTheDocument()
    expect(screen.getByText('Connection lost')).toBeInTheDocument()
    expect(container.textContent).not.toContain('UUID')
    const results = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })
    expect(results.violations).toEqual([])
  })
})