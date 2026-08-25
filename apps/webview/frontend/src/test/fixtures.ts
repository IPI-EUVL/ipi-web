import type { LiveResponse } from '../api/types'

export function makeLiveSnapshot(): LiveResponse {
  return {
    schema_version: '1',
    revision: 1,
    generated_at: 1_700_000_000,
    system: { state: 'ok', label: 'System OK', issues: [] },
    experiment: { phase: 'idle', details: null, reasons: [] },
    progress: { mode: 'none', current: null, target: null, unit: null, percent: null },
    queue: { remaining_count: 0, current_batch_remaining_count: 0 },
    batch: {
      name: null,
      selection_source: 'none',
      exposures: [],
      slots: [],
      unplaced_exposures: [],
      remaining_count: 0,
      possibly_truncated: false,
      authoritative: false,
      plan_entries: [],
    },
    stage: { state: 'idle', current_sample_number: null, position: { theta: 0, z: 0 } },
    subsystems: [],
    sources: {
      transport: { state: 'available', observed_at: 1_700_000_000, attempted_at: 1_700_000_000, error: null },
      history: { state: 'available', observed_at: 1_700_000_000, attempted_at: 1_700_000_000, error: null },
    },
  }
}