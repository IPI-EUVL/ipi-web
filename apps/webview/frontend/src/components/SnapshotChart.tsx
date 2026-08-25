import { RotateCcw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import uPlot, { type AlignedData } from 'uplot'
import 'uplot/dist/uPlot.min.css'

import type { GraphAnnotation, GraphAnnotationCategory, SnapshotGraphSeries } from '../api/experiments'
import { annotationPlugin, chartXExtent, elapsedUnit, elapsedValues, fixedRange, navigationPlugin, nearestAnnotation } from './chartUtils'

export function SnapshotChart({
  data,
  compact = false,
  followLatest = false,
  liveWindow,
  onPointClick,
  visibleAnnotationCategories,
}: {
  data: SnapshotGraphSeries
  compact?: boolean
  followLatest?: boolean
  liveWindow?: number
  onPointClick?: (pointIndex: number) => void
  visibleAnnotationCategories?: ReadonlySet<GraphAnnotationCategory>
}) {
  const hostRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<uPlot | null>(null)
  const hasInitialDataRef = useRef(false)
  const onPointClickRef = useRef(onPointClick)
  const pointCountRef = useRef(data.x.length)
  const annotationsRef = useRef<readonly GraphAnnotation[]>(data.annotations ?? [])
  const annotationExtentRef = useRef<[number, number]>([0, 1])
  const [tooltip, setTooltip] = useState<{ annotation: GraphAnnotation; left: number } | null>(null)
  const [yMinimum, yMaximum] = fixedRange(data.y)
  const elapsedTimeAxis = /time|runtime/i.test(data.x_label)
  const hasPointClick = onPointClick !== undefined
  const visibleAnnotations = (data.annotations ?? []).filter((annotation) => visibleAnnotationCategories?.has(annotation.category) ?? true)
  annotationExtentRef.current = chartXExtent(data.x, visibleAnnotations)

  useEffect(() => {
    onPointClickRef.current = onPointClick
    pointCountRef.current = data.x.length
  }, [data.x.length, onPointClick])

  useEffect(() => {
    annotationsRef.current = visibleAnnotations
    chartRef.current?.redraw?.()
  }, [visibleAnnotations])

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    hasInitialDataRef.current = false
    const height = compact ? 150 : 340
    const plot = new uPlot(
      {
        width: Math.max(host.clientWidth, 280),
        height,
        padding: compact ? [8, 8, 0, 0] : [12, 14, 0, 0],
        cursor: {
          drag: { x: true, y: false, setScale: true },
          bind: hasPointClick
            ? {
                click: (plot, _target, handler) => (event) => {
                  handler(event)
                  const pointIndex = plot.cursor.idx ?? plot.posToIdx(event.offsetX)
                  if (pointIndex >= 0 && pointIndex < pointCountRef.current) onPointClickRef.current?.(pointIndex)
                  return null
                },
              }
            : undefined,
        },
        legend: { show: false },
        scales: {
          x: { time: false },
          y: { auto: false, range: [0, 1] },
        },
        plugins: [annotationPlugin(annotationsRef, compact), ...(compact ? [] : [navigationPlugin(() => annotationExtentRef.current)])],
        axes: compact
          ? [{ stroke: '#62717e', grid: { stroke: '#29384655' }, size: 28 }, { stroke: '#62717e', grid: { stroke: '#29384655' }, size: 44 }]
          : [
              {
                label: elapsedTimeAxis ? (plot) => `Elapsed time (${elapsedUnit(plot).unit})` : data.x_label,
                values: elapsedTimeAxis ? elapsedValues : undefined,
                stroke: '#8d9ba7',
                grid: { stroke: '#29384688' },
                size: 46,
              },
              { label: data.y_label, stroke: '#8d9ba7', grid: { stroke: '#29384688' }, size: 62 },
            ],
        series: [
          {},
          {
            label: data.y_label,
            stroke: '#59c8e8',
            width: compact ? 1.5 : 1,
            points: hasPointClick ? { show: true, size: 8, width: 2, stroke: '#59c8e8', fill: '#071019' } : undefined,
          },
        ],
      },
      [[], []] as AlignedData,
      host,
    )
    chartRef.current = plot
    const onPointerMove = (event: PointerEvent) => {
      const extent = annotationExtentRef.current
      const value = plot.posToVal(event.clientX - plot.rect.left, 'x')
      const annotation = nearestAnnotation(annotationsRef.current, value, extent)
      setTooltip(annotation ? { annotation, left: event.clientX - plot.rect.left } : null)
    }
    const onPointerLeave = () => setTooltip(null)
    plot.over.addEventListener('pointermove', onPointerMove)
    plot.over.addEventListener('pointerleave', onPointerLeave)
    const resize = new ResizeObserver(() => {
      plot.setSize({ width: Math.max(host.clientWidth, 280), height })
    })
    resize.observe(host)
    return () => {
      resize.disconnect()
      plot.over.removeEventListener('pointermove', onPointerMove)
      plot.over.removeEventListener('pointerleave', onPointerLeave)
      chartRef.current = null
      plot.destroy()
    }
  }, [compact, data.x_label, data.y_label, elapsedTimeAxis, hasPointClick])

  useEffect(() => {
    const plot = chartRef.current
    if (!plot) return
    const initialData = !hasInitialDataRef.current
    plot.setData([data.x, data.y] as AlignedData, initialData && !followLatest)
    hasInitialDataRef.current = true
    plot.setScale('y', { min: yMinimum, max: yMaximum })
    if (initialData && !followLatest) {
      const [minimum, maximum] = annotationExtentRef.current
      plot.setScale('x', { min: minimum, max: maximum })
    }
    if (followLatest && data.x.length) {
      const [, maximum] = annotationExtentRef.current
      const [fullMinimum] = annotationExtentRef.current
      const minimum = liveWindow === undefined ? fullMinimum : Math.max(fullMinimum, maximum - liveWindow)
      plot.setScale('x', { min: minimum, max: maximum })
    }
  }, [data.x, data.y, followLatest, liveWindow, yMaximum, yMinimum])

  const resetZoom = () => {
    if (!chartRef.current) return
    const [minimum, maximum] = annotationExtentRef.current
    chartRef.current.setScale('x', { min: minimum, max: maximum })
  }

  return (
    <div className={`snapshot-chart ${compact ? 'is-compact' : ''}`}>
      {!compact && (
        <button type="button" className="chart-reset" onClick={resetZoom} title="Reset chart zoom" aria-label="Reset chart zoom">
          <RotateCcw size={15} aria-hidden="true" />
        </button>
      )}
      <div ref={hostRef} className="snapshot-chart-host" />
      {tooltip && !compact && <div className="chart-annotation-tooltip" style={{ left: Math.max(8, tooltip.left + 10) }}>
        <strong>{tooltip.annotation.label}</strong>
        <span>{tooltip.annotation.source}</span>
        <span>{tooltip.annotation.projection_quality.replace('_', ' ')}</span>
      </div>}
    </div>
  )
}