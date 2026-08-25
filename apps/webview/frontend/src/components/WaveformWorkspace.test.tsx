import { describe, expect, it, vi } from 'vitest'

import type { ExperimentDetail } from '../api/experiments'
import { orderSnapshotsByElapsed } from './WaveformWorkspace'

vi.mock('uplot', () => ({ default: class MockUPlot {} }))

function snapshot(snapshotId: string, finalSequence: number | null): ExperimentDetail['snapshots'][number] {
  return {
    snapshot_id: snapshotId,
    format: 'legacy_npz',
    waveform: { name: `snap_${snapshotId}.npz`, resource_type: 'snapshot', size_bytes: 1, available: true, downloadable: true, error: null },
    metadata: { name: `snap_${snapshotId}.json`, resource_type: 'snap_meta', size_bytes: 1, available: true, downloadable: true, error: null },
    final_sequence: finalSequence,
  }
}

describe('orderSnapshotsByElapsed', () => {
  it('uses capture sequences for snapshot chronology independently of graph points', () => {
    const snapshots = [snapshot('later', 10), snapshot('untimed', null), snapshot('first', 4)]
    const ordered = orderSnapshotsByElapsed(snapshots)

    expect(ordered.map(({ snapshot }) => snapshot.snapshot_id)).toEqual(['first', 'later', 'untimed'])
  })
})