import { fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SnapshotChart } from './SnapshotChart'

const plotInstances: Array<{
  setData: ReturnType<typeof vi.fn>
  setScale: ReturnType<typeof vi.fn>
  destroy: ReturnType<typeof vi.fn>
  posToIdx: ReturnType<typeof vi.fn>
  cursor: { idx: number | null }
  over: HTMLDivElement
}> = []

class ResizeObserverStub {
  observe() {}
  disconnect() {}
}

vi.stubGlobal('ResizeObserver', ResizeObserverStub)

vi.mock('uplot', () => {
  class MockUPlot {
    setData = vi.fn()
    setScale = vi.fn()
    destroy = vi.fn()
    over = document.createElement('div')
    cursor = { idx: null }
    posToIdx = vi.fn(() => 0)

    constructor(options: { cursor?: { bind?: { click?: (plot: MockUPlot, target: HTMLElement, handler: (event: MouseEvent) => null) => (event: MouseEvent) => null } } }) {
      const clickListener = options.cursor?.bind?.click?.(this, this.over, () => null)
      if (clickListener) this.over.addEventListener('click', clickListener)
      plotInstances.push(this)
    }

    setSize = vi.fn()
  }
  return { default: MockUPlot }
})

vi.mock('./chartUtils', () => ({
  annotationPlugin: () => ({}),
  chartXExtent: (values: number[], annotations: Array<{ x: number; x_end: number | null }>) => {
    const extent = [...values, ...annotations.flatMap((annotation) => annotation.x_end === null ? [annotation.x] : [annotation.x, annotation.x_end])]
    return [Math.min(...extent), Math.max(...extent)] as [number, number]
  },
  elapsedUnit: () => ({ factor: 1, unit: 's' }),
  elapsedValues: () => [],
  fixedRange: (values: number[]) => [Math.min(...values), Math.max(...values)] as [number, number],
  navigationPlugin: () => ({}),
  nearestAnnotation: () => null,
}))

const baseSeries = {
  schema_version: '2' as const,
  snapshot_id: '00000000-0000-0000-0000-000000000000',
  series: 'dose' as const,
  x_label: 'Elapsed time (s)',
  y_label: 'Cumulative dose (mJ/cm²)',
  x: [0, 1],
  y: [1, 2],
  point_count: 2,
  rolling_window: 1,
  annotations: [],
  issues: [],
}

describe('SnapshotChart', () => {
  afterEach(() => {
    plotInstances.length = 0
  })

  it('preserves x-axis zoom when refreshed series values arrive', () => {
    const { rerender } = render(<SnapshotChart data={baseSeries} />)
    const plot = plotInstances[0]

    expect(plotInstances).toHaveLength(1)
    expect(plot.setData).toHaveBeenLastCalledWith([baseSeries.x, baseSeries.y], true)

    const refreshed = { ...baseSeries, x: [0, 1, 2], y: [1, 2, 4], point_count: 3 }
    rerender(<SnapshotChart data={refreshed} />)

    expect(plotInstances).toHaveLength(1)
    expect(plot.setData).toHaveBeenLastCalledWith([refreshed.x, refreshed.y], false)
  })

  it('reports the clicked timeline point index', () => {
    const onPointClick = vi.fn()
    render(<SnapshotChart data={baseSeries} onPointClick={onPointClick} />)
    const plot = plotInstances[0]
    plot.cursor.idx = 1

    fireEvent.click(plot.over)

    expect(onPointClick).toHaveBeenCalledWith(1)
  })

  it('uses annotation bounds for initial and reset x-axis extent', () => {
    const annotated = {
      ...baseSeries,
      annotations: [{ event_id: 'event', category: 'lifecycle' as const, kind: 'point' as const, label: 'CAN_START', x: -2, x_end: null, value: null, source: 'controller', producer_unix_ns: 1, projection_quality: 'producer' as const }],
    }
    render(<SnapshotChart data={annotated} />)
    const plot = plotInstances[0]

    expect(plot.setScale).toHaveBeenCalledWith('x', { min: -2, max: 1 })
    fireEvent.click(document.querySelector('[aria-label="Reset chart zoom"]')!)
    expect(plot.setScale).toHaveBeenLastCalledWith('x', { min: -2, max: 1 })
  })
})