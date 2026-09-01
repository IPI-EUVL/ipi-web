import type { AlignedData } from 'uplot'

export type DoseComparisonLine = {
  key: string
  label: string
  color: string
  x: number[]
  y: number[]
  dashed?: boolean
}

export function alignDoseComparisonSeries(lines: DoseComparisonLine[]): AlignedData {
  const x = [...new Set(lines.flatMap((line) => line.x))]
    .filter(Number.isFinite)
    .sort((left, right) => left - right)
  const values = lines.map((line) => {
    const points = line.x
      .map((value, index) => [value, line.y[index]] as const)
      .filter(([pointX, pointY]) => Number.isFinite(pointX) && Number.isFinite(pointY))
      .sort(([left], [right]) => left - right)
    let pointIndex = 0
    let current: number | null = null
    return x.map((value) => {
      while (pointIndex < points.length && points[pointIndex][0] <= value) {
        current = points[pointIndex][1]
        pointIndex += 1
      }
      return current
    })
  })
  return [x, ...values] as AlignedData
}