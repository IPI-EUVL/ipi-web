import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { makeLiveSnapshot } from '../test/fixtures'
import { StatusBand } from './StatusBand'

describe('StatusBand', () => {
  it('renders idle dose and time as yellow N/A sources', () => {
    const snapshot = makeLiveSnapshot()
    snapshot.sources.dose = { state: 'not_applicable', observed_at: null, attempted_at: 1_700_000_000, error: null }
    snapshot.sources.time = { state: 'not_applicable', observed_at: null, attempted_at: 1_700_000_000, error: null }

    const { container } = render(<StatusBand snapshot={snapshot} connectionState="live" />)

    expect(screen.getAllByText('N/A')).toHaveLength(2)
    expect(container.querySelectorAll('.source-not_applicable')).toHaveLength(2)
  })
})