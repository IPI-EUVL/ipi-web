import { useEffect, useState, type KeyboardEvent } from 'react'
import { Crosshair, Disc3 } from 'lucide-react'

import { deriveStageSlots, formatNumber, type StageSlotView } from '../api/selectors'
import type { LiveResponse } from '../api/types'
import { ExposureStateLabel } from './ExposureStateLabel'

type SlotGeometry = { sampleNumber: number; x: number; y: number }

const geometry: SlotGeometry[] = [
  { sampleNumber: 1, x: 92, y: 62 },
  { sampleNumber: 2, x: 72, y: 80 },
  { sampleNumber: 3, x: 52, y: 80 },
  { sampleNumber: 4, x: 32, y: 62 },
  { sampleNumber: 5, x: 32, y: 38 },
  { sampleNumber: 6, x: 52, y: 20 },
  { sampleNumber: 7, x: 72, y: 20 },
  { sampleNumber: 8, x: 92, y: 38 },
  { sampleNumber: 9, x: 72, y: 62 },
  { sampleNumber: 10, x: 52, y: 62 },
  { sampleNumber: 11, x: 52, y: 38 },
  { sampleNumber: 12, x: 72, y: 38 },
]

function SlotDetails({ slot }: { slot: StageSlotView }) {
  const summary = slot.summary
  return (
    <div className="slot-details" aria-live="polite">
      <div className="slot-details-heading">
        <span>Sample {slot.sampleNumber}</span>
        <ExposureStateLabel state={slot.state} />
      </div>
      <dl>
        <div><dt>Attempts</dt><dd>{summary?.attempt_count ?? slot.attempts.length}</dd></div>
        <div><dt>Target dose</dt><dd>{summary?.first_target_dose ? `${formatNumber(summary.first_target_dose)} mJ/cm2` : '—'}</dd></div>
        <div><dt>Target time</dt><dd>{summary?.first_target_time ? `${formatNumber(summary.first_target_time)} s` : '—'}</dd></div>
        <div><dt>Actual dose</dt><dd>{summary ? `${formatNumber(summary.cumulative_actual_dose)} mJ/cm2` : '—'}</dd></div>
        <div><dt>Actual time</dt><dd>{summary ? `${formatNumber(summary.cumulative_actual_time)} s` : '—'}</dd></div>
        <div><dt>On stage</dt><dd>{slot.isStageCurrent ? 'Yes' : 'No'}</dd></div>
      </dl>
      {slot.missedTarget && <p className="target-missed-note">Target not met</p>}
      {summary?.abort_reasons.map((reason, index) => <p className="slot-failure" key={`${reason}-${index}`}>{reason}</p>)}
    </div>
  )
}

export function SampleStage({ snapshot }: { snapshot: LiveResponse }) {
  const slots = deriveStageSlots(snapshot)
  const firstRelevant = slots.find((slot) => slot.state !== 'unknown')?.sampleNumber ?? 1
  const [selectedSample, setSelectedSample] = useState(snapshot.stage.current_sample_number ?? firstRelevant)
  const selected = slots[selectedSample - 1] ?? slots[0]

  useEffect(() => {
    if (snapshot.stage.current_sample_number) setSelectedSample(snapshot.stage.current_sample_number)
  }, [snapshot.stage.current_sample_number])

  function selectWithKeyboard(event: KeyboardEvent<SVGGElement>, sampleNumber: number) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      setSelectedSample(sampleNumber)
    }
  }

  return (
    <div className="stage-layout">
      <div className="stage-visual-wrap">
        <svg className="stage-visual" viewBox="0 0 112 100" role="group" aria-label="Twelve-position sample stage with chamber door at the left edge">
          <title>Twelve-position sample stage with chamber door at the left edge</title>
          <circle className="stage-rail stage-rail-outer" cx="62" cy="50" r="42" />
          <circle className="stage-rail stage-rail-inner" cx="62" cy="50" r="25" />
          <circle className="stage-hub" cx="62" cy="50" r="9" />
          <path className="stage-crosshair" d="M62 38v24M50 50h24" />
          <g className="stage-door" aria-hidden="true">
            <path d="M19 34h-5v32h5" />
            <text x="8" y="50" textAnchor="middle" transform="rotate(-90 8 50)">DOOR</text>
          </g>
          {geometry.map((geometrySlot) => {
            const slot = slots[geometrySlot.sampleNumber - 1]
            const selectedClass = selectedSample === slot.sampleNumber ? ' is-selected' : ''
            const stageClass = slot.isStageCurrent ? ' is-stage-current' : ''
            const missedClass = slot.missedTarget ? ' is-target-missed' : ''
            return (
              <g
                key={slot.sampleNumber}
                className={`stage-slot stage-slot-${slot.state}${selectedClass}${stageClass}${missedClass}`}
                transform={`translate(${geometrySlot.x} ${geometrySlot.y})`}
                role="button"
                tabIndex={0}
                data-sample-number={slot.sampleNumber}
                aria-label={`Sample ${slot.sampleNumber}, ${slot.state}${slot.missedTarget ? ', target not met' : ''}${slot.isStageCurrent ? ', positioned on stage' : ''}`}
                aria-pressed={selectedSample === slot.sampleNumber}
                onClick={() => setSelectedSample(slot.sampleNumber)}
                onKeyDown={(event) => selectWithKeyboard(event, slot.sampleNumber)}
              >
                <rect x="-5.5" y="-5" width="11" height="10" />
                <text textAnchor="middle" dominantBaseline="central">{slot.sampleNumber}</text>
              </g>
            )
          })}
          <g className="stage-center-label" aria-hidden="true">
            <Disc3 size={8} x={58} y={41} />
            <text x="62" y="53" textAnchor="middle">{snapshot.stage.state}</text>
          </g>
        </svg>
        <div className="stage-position">
          <Crosshair size={14} aria-hidden="true" />
          <span>θ {snapshot.stage.position ? formatNumber(snapshot.stage.position.theta, 3) : '—'}</span>
          <span>z {snapshot.stage.position ? formatNumber(snapshot.stage.position.z, 3) : '—'}</span>
        </div>
      </div>
      <SlotDetails slot={selected} />
    </div>
  )
}