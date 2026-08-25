import uPlot from 'uplot'

import type { GraphAnnotation } from '../api/experiments'

export function fixedRange(values: readonly (number | null | undefined)[]): [number, number] {
  if (values.length === 0) return [-1, 1]
  let minimum = Number.POSITIVE_INFINITY
  let maximum = Number.NEGATIVE_INFINITY
  for (const value of values) {
    if (value === null || value === undefined || !Number.isFinite(value)) continue
    minimum = Math.min(minimum, value)
    maximum = Math.max(maximum, value)
  }
  if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) return [-1, 1]
  const span = maximum - minimum
  const padding = span > 0 ? span * 0.05 : Math.max(Math.abs(maximum) * 0.05, 1e-9)
  return [minimum - padding, maximum + padding]
}

export function elapsedUnit(plot: uPlot) {
  const minimum = plot.scales.x.min ?? 0
  const maximum = plot.scales.x.max ?? minimum
  const span = Math.abs(maximum - minimum)
  if (span < 1e-6) return { factor: 1e9, unit: 'ns' }
  if (span < 1e-3) return { factor: 1e6, unit: 'µs' }
  if (span < 1) return { factor: 1e3, unit: 'ms' }
  return { factor: 1, unit: 's' }
}

export const elapsedValues: uPlot.Axis.DynamicValues = (plot, splits) => {
  const { factor } = elapsedUnit(plot)
  const scaledSpan = Math.abs((plot.scales.x.max ?? 0) - (plot.scales.x.min ?? 0)) * factor
  const digits = scaledSpan < 1 ? 3 : scaledSpan < 10 ? 2 : 1
  return splits.map((value) => (value * factor).toLocaleString(undefined, { maximumFractionDigits: digits }))
}

export function chartXExtent(values: readonly number[], annotations: readonly GraphAnnotation[]): [number, number] {
  let minimum = Number.POSITIVE_INFINITY
  let maximum = Number.NEGATIVE_INFINITY
  const include = (value: number) => {
    if (!Number.isFinite(value)) return
    minimum = Math.min(minimum, value)
    maximum = Math.max(maximum, value)
  }
  for (const value of values) include(value)
  for (const annotation of annotations) {
    include(annotation.x)
    if (annotation.x_end !== null) include(annotation.x_end)
  }
  if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) return [0, 1]
  if (minimum === maximum) return [minimum - 1, maximum + 1]
  return [minimum, maximum]
}

type AnnotationLabelPosition = {
  annotation: GraphAnnotation
  x: number
  lane: number
}

export function annotationLabelPositions(
  annotations: readonly GraphAnnotation[],
  canvasX: (value: number) => number,
  measureText: (label: string) => number,
  bounds: { left: number; right: number },
): AnnotationLabelPosition[] {
  const gap = 4
  const labels = annotations
    .filter((annotation) => annotation.kind === 'point')
    .map((annotation) => {
      const anchor = canvasX(annotation.x)
      const width = measureText(annotation.label)
      const preferred = anchor + gap
      const x = preferred + width <= bounds.right
        ? preferred
        : anchor - gap - width >= bounds.left
          ? anchor - gap - width
          : Math.max(bounds.left, Math.min(preferred, bounds.right - width))
      return { annotation, x, right: x + width }
    })
    .sort((left, right) => left.x - right.x || left.annotation.x - right.annotation.x || left.annotation.label.localeCompare(right.annotation.label))

  const laneEnds: number[] = []
  return labels.map(({ annotation, x, right }) => {
    let lane = laneEnds.findIndex((end) => x >= end + gap)
    if (lane === -1) {
      lane = laneEnds.length
      laneEnds.push(right)
    } else {
      laneEnds[lane] = right
    }
    return { annotation, x, lane }
  })
}

export function annotationPlugin(
  annotationsRef: { current: readonly GraphAnnotation[] },
  compact: boolean,
): uPlot.Plugin {
  const colors: Record<GraphAnnotation['category'], string> = {
    lifecycle: '#e9b85f',
    triggers: '#68d391',
    transmitting: '#59c8e8',
  }
  const canvasX = (plot: uPlot, value: number) => {
    const position = plot.valToPos(value, 'x', true)
    return Math.max(plot.bbox.left, Math.min(plot.bbox.left + plot.bbox.width, position))
  }
  return {
    hooks: {
      drawClear: [plot => {
        const context = plot.ctx
        context.save()
        for (const annotation of annotationsRef.current) {
          if (annotation.kind !== 'interval' || annotation.value !== true || annotation.x_end === null) continue
          const left = canvasX(plot, annotation.x)
          const right = canvasX(plot, annotation.x_end)
          if (right <= left) continue
          context.fillStyle = `${colors[annotation.category]}20`
          context.fillRect(left, plot.bbox.top, right - left, plot.bbox.height)
        }
        context.restore()
      }],
      draw: [plot => {
        const context = plot.ctx
        context.save()
        context.lineWidth = 1
        context.font = '10px "IBM Plex Mono", monospace'
        context.textBaseline = 'top'
        for (const annotation of annotationsRef.current) {
          const x = canvasX(plot, annotation.x)
          const color = colors[annotation.category]
          context.strokeStyle = color
          context.setLineDash(annotation.kind === 'interval' ? [3, 3] : [])
          context.beginPath()
          context.moveTo(x, plot.bbox.top)
          context.lineTo(x, plot.bbox.top + plot.bbox.height)
          context.stroke()
        }
        if (!compact) {
          const xMinimum = plot.scales.x.min ?? Number.NEGATIVE_INFINITY
          const xMaximum = plot.scales.x.max ?? Number.POSITIVE_INFINITY
          const labelPositions = annotationLabelPositions(
            annotationsRef.current.filter((annotation) => annotation.x >= xMinimum && annotation.x <= xMaximum),
            (value) => canvasX(plot, value),
            (label) => context.measureText(label).width,
            { left: plot.bbox.left, right: plot.bbox.left + plot.bbox.width },
          )
          for (const { annotation, x, lane } of labelPositions) {
            context.fillStyle = colors[annotation.category]
            context.fillText(annotation.label, x, plot.bbox.top + 4 + lane * 13)
          }
        }
        context.setLineDash([])
        context.restore()
      }],
    },
  }
}

export function nearestAnnotation(
  annotations: readonly GraphAnnotation[],
  value: number,
  fullExtent: readonly [number, number],
): GraphAnnotation | null {
  const tolerance = Math.max((fullExtent[1] - fullExtent[0]) * 0.015, 1e-9)
  let closest: GraphAnnotation | null = null
  let distance = Number.POSITIVE_INFINITY
  let boundaryPriority = Number.POSITIVE_INFINITY
  for (const annotation of annotations) {
    const candidates = annotation.x_end === null
      ? [{ value: annotation.x, priority: 0 }]
      : [{ value: annotation.x, priority: 0 }, { value: annotation.x_end, priority: 1 }]
    for (const candidate of candidates) {
      const nextDistance = Math.abs(value - candidate.value)
      if (nextDistance < distance || (nextDistance === distance && candidate.priority < boundaryPriority)) {
        closest = annotation
        distance = nextDistance
        boundaryPriority = candidate.priority
      }
    }
  }
  return distance <= tolerance ? closest : null
}

export function navigationPlugin(fullExtent?: () => [number, number]): uPlot.Plugin {
  let cleanup = () => {}
  const syncScale = (plot: uPlot) => {
    plot.over.dataset.xMinimum = String(plot.scales.x.min ?? '')
    plot.over.dataset.xMaximum = String(plot.scales.x.max ?? '')
    plot.over.dataset.yMinimum = String(plot.scales.y.min ?? '')
    plot.over.dataset.yMaximum = String(plot.scales.y.max ?? '')
    plot.over.dataset.elapsedUnit = elapsedUnit(plot).unit
  }
  return {
    hooks: {
      ready: (plot) => {
        const over = plot.over
        const dataExtent = () => {
          const xValues = plot.data[0]
          return xValues.length ? [Number(xValues[0]), Number(xValues[xValues.length - 1])] as const : [0, 1] as const
        }
        const clampRange = (minimum: number, maximum: number) => {
          const [fullMinimum, fullMaximum] = fullExtent?.() ?? dataExtent()
          const width = Math.min(maximum - minimum, fullMaximum - fullMinimum)
          const boundedMinimum = Math.max(fullMinimum, Math.min(minimum, fullMaximum - width))
          return [boundedMinimum, boundedMinimum + width] as const
        }
        const wheel = (event: WheelEvent) => {
          const minimum = plot.scales.x.min
          const maximum = plot.scales.x.max
          if (minimum === undefined || maximum === undefined || maximum <= minimum) return
          event.preventDefault()
          const cursorValue = plot.posToVal(event.clientX - plot.rect.left, 'x')
          const factor = event.deltaY < 0 ? 0.78 : 1.28
          const [nextMinimum, nextMaximum] = clampRange(
            cursorValue - (cursorValue - minimum) * factor,
            cursorValue + (maximum - cursorValue) * factor,
          )
          plot.setScale('x', { min: nextMinimum, max: nextMaximum })
        }
        let dragStart: { x: number; minimum: number; maximum: number } | null = null
        const pointerDown = (event: PointerEvent) => {
          if (!event.shiftKey && event.button !== 1) return
          const minimum = plot.scales.x.min
          const maximum = plot.scales.x.max
          if (minimum === undefined || maximum === undefined) return
          event.preventDefault()
          event.stopPropagation()
          dragStart = { x: event.clientX, minimum, maximum }
          over.setPointerCapture(event.pointerId)
        }
        const pointerMove = (event: PointerEvent) => {
          if (!dragStart) return
          event.preventDefault()
          event.stopPropagation()
          const delta = plot.posToVal(dragStart.x - plot.rect.left, 'x') - plot.posToVal(event.clientX - plot.rect.left, 'x')
          const [minimum, maximum] = clampRange(dragStart.minimum + delta, dragStart.maximum + delta)
          plot.setScale('x', { min: minimum, max: maximum })
        }
        const pointerUp = (event: PointerEvent) => {
          if (!dragStart) return
          dragStart = null
          if (over.hasPointerCapture(event.pointerId)) over.releasePointerCapture(event.pointerId)
        }
        over.addEventListener('wheel', wheel, { passive: false })
        over.addEventListener('pointerdown', pointerDown, true)
        over.addEventListener('pointermove', pointerMove, true)
        over.addEventListener('pointerup', pointerUp, true)
        over.addEventListener('pointercancel', pointerUp, true)
        cleanup = () => {
          over.removeEventListener('wheel', wheel)
          over.removeEventListener('pointerdown', pointerDown, true)
          over.removeEventListener('pointermove', pointerMove, true)
          over.removeEventListener('pointerup', pointerUp, true)
          over.removeEventListener('pointercancel', pointerUp, true)
        }
        syncScale(plot)
      },
      setScale: (plot, scaleKey) => {
        if (scaleKey === 'x' || scaleKey === 'y') syncScale(plot)
      },
      destroy: () => cleanup(),
    },
  }
}
