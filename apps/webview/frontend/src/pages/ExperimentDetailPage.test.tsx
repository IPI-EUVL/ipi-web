import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ExperimentDetail, ExposureEventTimeline } from '../api/experiments'

const hooks = vi.hoisted(() => ({
  useExperiment: vi.fn(),
  useExposureEvents: vi.fn(),
  useRunDoseSeries: vi.fn(),
}))

vi.mock('uplot', () => ({ default: class MockUPlot {} }))

vi.mock('../api/experiments', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/experiments')>()),
  useExperiment: hooks.useExperiment,
  useExposureEvents: hooks.useExposureEvents,
  useRunDoseSeries: hooks.useRunDoseSeries,
}))

import { ExperimentDetailPage } from './ExperimentDetailPage'

const runId = '31b1a767-b5c0-4e86-8c62-a8ea492a7009'

const detail: ExperimentDetail = {
  schema_version: '1',
  summary: {
    run_id: runId,
    created_at: 1_700_000_000,
    name: 'Timeline fixture',
    description: '',
    sample: null,
    operator: null,
    zr_filter: null,
    target_dose: null,
    target_time: null,
    actual_dose: null,
    runtime: null,
    effective_dose_rate: null,
    exposed_thickness_nm: null,
    blank_thickness_nm: null,
    percent_development: null,
    status: 'STOPPED',
    end_reason: null,
  },
  settings: {},
  metadata: {},
  end_metadata: null,
  tags: {},
  resources: [],
  snapshots: [],
  metrics: {
    measurements: [],
    exposed_average_nm: null,
    blank_average_nm: null,
    percent_development: null,
    degraded: false,
    error: null,
  },
  log_range: { event_id: 'log-event', created_at: null, ended_at: null, complete: true },
  issues: [],
}

const timeline: ExposureEventTimeline = {
  schema_version: '1',
  run_id: runId,
  events: [
    {
      event_id: 'lifecycle-event', stream_id: 'controller-stream', stream_name: 'controller.lifecycle', sequence: 1,
      kind: 'lifecycle.phase', producer_unix_ns: 1_700_000_000_000_000, producer_monotonic_ns: null,
      ingest_unix_ns: 1_700_000_000_000_100, payload: { phase: 'PREINIT' }, capture_session_id: null,
      next_sequence: null, runtime_seconds: null,
    },
    {
      event_id: 'trigger-event', stream_id: 'acquisition-stream', stream_name: 'acquisition.timing', sequence: 2,
      kind: 'timing.triggers_enabled', producer_unix_ns: 1_700_000_001_000_000, producer_monotonic_ns: null,
      ingest_unix_ns: 1_700_000_001_000_100, payload: { value: true }, capture_session_id: null,
      next_sequence: 42, runtime_seconds: 0,
    },
  ],
  complete: false,
  issues: ['The acquisition stream was not closed.'],
  wall_time_origin_unix_ns: 1_700_000_000_000_000,
}

describe('ExperimentDetailPage events tab', () => {
  beforeEach(() => {
    hooks.useExperiment.mockReturnValue({ data: detail, error: null, isLoading: false, isFetching: false })
    hooks.useExposureEvents.mockReturnValue({ data: timeline, error: null, isLoading: false })
    hooks.useRunDoseSeries.mockReturnValue({
      data: { status: 'complete', points: [], annotations: [], issues: [], errors: [], total_snapshots: 0, completed_snapshots: 0 },
      isLoading: false,
    })
  })

  it('shows raw integrity state and filters events by source and category', () => {
    render(<ExperimentDetailPage runId={runId} />)

    fireEvent.click(screen.getByRole('button', { name: 'Events' }))
    const eventTimeline = screen.getByText(/Timeline integrity warning/).closest('.event-timeline')
    if (!(eventTimeline instanceof HTMLElement)) throw new Error('Expected an event timeline container.')
    const events = within(eventTimeline)
    expect(events.getByText(/acquisition stream was not closed/i)).toBeInTheDocument()
    expect(events.getByText('PREINIT')).toBeInTheDocument()
    expect(events.getByText('next pulse 42')).toBeInTheDocument()

    fireEvent.change(events.getByRole('textbox', { name: 'Source' }), { target: { value: 'acquisition' } })
    expect(events.queryByText('PREINIT')).not.toBeInTheDocument()
    expect(events.getByText('next pulse 42')).toBeInTheDocument()

    fireEvent.click(events.getByRole('checkbox', { name: 'Triggers' }))
    expect(events.getByText('No recorded events match the active filters.')).toBeInTheDocument()
  })
})