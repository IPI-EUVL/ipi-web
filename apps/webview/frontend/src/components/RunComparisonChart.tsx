import { useEffect, useRef } from 'react'
import uPlot, { type AlignedData } from 'uplot'

import { elapsedUnit, elapsedValues, fixedRange, navigationPlugin } from './chartUtils'

export type ComparisonTrace = {
  id: string
  label: string
  color: string
  x: number[]
  y: number[]
  visible: boolean
}

export function RunComparisonChart({
  traces,
  yLabel,
}: {
  traces: ComparisonTrace[]
  yLabel: string
}) {
  const hostRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const visibleTraces = traces.filter((trace) => trace.visible && trace.x.length > 0)
    if (visibleTraces.length === 0) return
    const data = uPlot.join(visibleTraces.map((trace) => [trace.x, trace.y] as AlignedData))
    const [yMinimum, yMaximum] = fixedRange(visibleTraces.flatMap((trace) => trace.y))
    const height = 420
    const plot = new uPlot(
      {
        width: Math.max(host.clientWidth, 320),
        height,
        padding: [12, 14, 0, 0],
        cursor: { drag: { x: true, y: false, setScale: true } },
        legend: { show: false },
        scales: {
          x: { time: false },
          y: { auto: false, range: [yMinimum, yMaximum] },
        },
        plugins: [navigationPlugin()],
        axes: [
          {
            label: (currentPlot) => `Elapsed time (${elapsedUnit(currentPlot).unit})`,
            values: elapsedValues,
            stroke: '#8d9ba7',
            grid: { stroke: '#29384688' },
            size: 46,
          },
          { label: yLabel, stroke: '#8d9ba7', grid: { stroke: '#29384688' }, size: 68 },
        ],
        series: [
          {},
          ...visibleTraces.map((trace) => ({ label: trace.label, stroke: trace.color, width: 1.5 })),
        ],
      },
      data,
      host,
    )
    const resize = new ResizeObserver(() => plot.setSize({ width: Math.max(host.clientWidth, 320), height }))
    resize.observe(host)
    return () => {
      resize.disconnect()
      plot.destroy()
    }
  }, [traces, yLabel])

  return <div className="run-comparison-chart" ref={hostRef} />
}