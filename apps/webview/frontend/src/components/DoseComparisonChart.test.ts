import { describe, expect, it } from 'vitest'

import { alignDoseComparisonSeries, type DoseComparisonLine } from './doseComparisonSeries'

describe('alignDoseComparisonSeries', () => {
  it('holds each cumulative value across the shared wall-time axis', () => {
    const lines: DoseComparisonLine[] = [
      { key: 'canonical', label: 'Canonical', color: '#000', x: [0, 2], y: [0, 2] },
      { key: 'captured', label: 'Captured', color: '#111', x: [1, 2], y: [10, 20] },
    ]

    const aligned = alignDoseComparisonSeries(lines)

    expect(aligned[0]).toEqual([0, 1, 2])
    expect(aligned[1]).toEqual([0, 0, 2])
    expect(aligned[2]).toEqual([null, 10, 20])
  })
})