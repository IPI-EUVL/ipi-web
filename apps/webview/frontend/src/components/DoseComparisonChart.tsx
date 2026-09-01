import { RotateCcw } from 'lucide-react'
import { useEffect, useMemo, useRef } from 'react'
import uPlot, { type AlignedData } from 'uplot'

import { elapsedUnit, elapsedValues, navigationPlugin } from './chartUtils'
import { alignDoseComparisonSeries, type DoseComparisonLine } from './doseComparisonSeries'

function yRange(lines: DoseComparisonLine[]): [number, number] {
  const values = lines.flatMap((line) => line.y).filter(Number.isFinite)
  if (values.length === 0) return [0, 1]
  const minimum = Math.min(0, ...values)
  const maximum = Math.max(0, ...values)
  if (minimum === maximum) return [minimum - 0.5, maximum + 0.5]
  const padding = (maximum - minimum) * 0.08
  return [minimum - padding, maximum + padding]
}

export function DoseComparisonChart({ lines }: { lines: DoseComparisonLine[] }) {
  const hostRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<uPlot | null>(null)
  const data = useMemo(() => alignDoseComparisonSeries(lines), [lines])
  const [minimumY, maximumY] = useMemo(() => yRange(lines), [lines])
  const configKey = lines.map(({ key, label, color, dashed }) => `${key}:${label}:${color}:${dashed ?? false}`).join('|')
  const xExtent = useMemo<[number, number]>(() => {
    const x = data[0]
    if (x.length === 0) return [0, 1]
    const minimum = Number(x[0])
    const maximum = Number(x[x.length - 1])
    return minimum === maximum ? [minimum, minimum + 1] : [minimum, maximum]
  }, [data])
  const xExtentRef = useRef(xExtent)
  xExtentRef.current = xExtent

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const height = 340
    const plot = new uPlot(
      {
        width: Math.max(host.clientWidth, 280),
        height,
        padding: [12, 14, 0, 0],
        cursor: { drag: { x: true, y: false, setScale: true } },
        legend: { show: false },
        scales: {
          x: { time: false },
          y: { auto: false, range: [0, 1] },
        },
        plugins: [navigationPlugin(() => xExtentRef.current)],
        axes: [
          {
            label: (activePlot) => `Wall elapsed time (${elapsedUnit(activePlot).unit})`,
            values: elapsedValues,
            stroke: '#8d9ba7',
            grid: { stroke: '#29384688' },
            size: 46,
          },
          {
            label: 'Cumulative dose (mJ/cm²)',
            stroke: '#8d9ba7',
            grid: { stroke: '#29384688' },
            size: 62,
          },
        ],
        series: [
          {},
          ...lines.map((line) => ({
            label: line.label,
            stroke: line.color,
            width: 1.5,
            dash: line.dashed ? [8, 5] : undefined,
            spanGaps: true,
          })),
        ],
      },
      [[], ...lines.map(() => [])] as AlignedData,
      host,
    )
    chartRef.current = plot
    const resize = new ResizeObserver(() => {
      plot.setSize({ width: Math.max(host.clientWidth, 280), height })
    })
    resize.observe(host)
    return () => {
      resize.disconnect()
      chartRef.current = null
      plot.destroy()
    }
  }, [configKey, lines])

  useEffect(() => {
    const plot = chartRef.current
    if (!plot) return
    plot.setData(data)
    plot.setScale('y', { min: minimumY, max: maximumY })
    plot.setScale('x', { min: xExtent[0], max: xExtent[1] })
  }, [data, maximumY, minimumY, xExtent])

  const resetZoom = () => {
    chartRef.current?.setScale('x', { min: xExtentRef.current[0], max: xExtentRef.current[1] })
  }

  return (
    <div className="snapshot-chart dose-comparison-chart">
      <button type="button" className="chart-reset" onClick={resetZoom} title="Reset chart zoom" aria-label="Reset chart zoom">
        <RotateCcw size={15} aria-hidden="true" />
      </button>
      <div ref={hostRef} className="snapshot-chart-host" />
      <div className="dose-comparison-legend" aria-label="Dose comparison legend">
        {lines.map((line) => <span key={line.key}><i style={{ backgroundColor: line.color }} />{line.label}</span>)}
      </div>
    </div>
  )
}