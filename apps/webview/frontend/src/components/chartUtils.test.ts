import { describe, expect, it, vi } from 'vitest'

vi.mock('uplot', () => ({ default: class MockUPlot {} }))

import type { GraphAnnotation } from '../api/experiments'
import { annotationLabelPositions, chartXExtent, nearestAnnotation } from './chartUtils'

function timingInterval(label: string, x: number, xEnd: number, value: boolean): GraphAnnotation {
  return {
    event_id: label,
    category: 'triggers',
    kind: 'interval',
    label,
    x,
    x_end: xEnd,
    value,
    source: 'acquisition.timing',
    producer_unix_ns: 0,
    projection_quality: 'producer',
  }
}

function lifecycleAnnotation(label: string, x: number): GraphAnnotation {
  return {
    event_id: label,
    category: 'lifecycle',
    kind: 'point',
    label,
    x,
    x_end: null,
    value: null,
    source: 'controller.lifecycle',
    producer_unix_ns: 0,
    projection_quality: 'producer',
  }
}

describe('chartXExtent', () => {
  it('derives extents from a large waveform series without spreading it into a call', () => {
    const samples = Array.from({ length: 250_000 }, (_value, index) => index / 10)

    expect(chartXExtent(samples, [])).toEqual([0, 24_999.9])
  })
})

describe('nearestAnnotation', () => {
  it('reports the incoming state at a shared interval boundary', () => {
    const disabled = timingInterval('Laser disabled', 0, 5, false)
    const enabled = timingInterval('Laser enabled', 5, 10, true)

    expect(nearestAnnotation([disabled, enabled], 5, [0, 10])).toBe(enabled)
  })

  it('reports the incoming closed state when an enabled interval ends', () => {
    const opened = timingInterval('Opened chopper', 0, 5, true)
    const shut = timingInterval('Shut chopper', 5, 10, false)

    expect(nearestAnnotation([opened, shut], 5, [0, 10])).toBe(shut)
  })
})

describe('annotationLabelPositions', () => {
  it('stacks overlapping labels and positions a right-edge label beside its marker', () => {
    const positions = annotationLabelPositions(
      [
        lifecycleAnnotation('CAN_START', 0),
        lifecycleAnnotation('PREINIT', 1),
        lifecycleAnnotation('STOPPED', 10),
      ],
      (value) => value * 10,
      (label) => label.length * 6,
      { left: 0, right: 100 },
    )

    expect(positions.map(({ annotation, x, lane }) => [annotation.label, x, lane])).toEqual([
      ['CAN_START', 4, 0],
      ['PREINIT', 14, 1],
      ['STOPPED', 54, 2],
    ])
  })
})