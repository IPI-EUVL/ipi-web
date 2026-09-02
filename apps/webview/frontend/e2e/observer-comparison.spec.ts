import { expect, test } from '@playwright/test'

import type {
  ExperimentDetail,
  ObserverDoseComparison,
  RunDoseSeries,
  SnapshotGraphSeries,
} from '../src/api/experiments'

const runId = '31b1a767-b5c0-4e86-8c62-a8ea492a7009'
const snapshotId = '7fa8c6e2-699b-4db9-9db7-f68229af44e9'

const detail = {
  schema_version: '1',
  summary: {
    run_id: runId,
    created_at: 1_700_000_000,
    name: 'Dual-source exposure',
    description: 'Comparison fixture',
    sample: 'HSQ-04',
    operator: 'operator-a',
    zr_filter: '200 nm',
    target_dose: 8,
    target_time: null,
    actual_dose: 7.8,
    runtime: 2,
    effective_dose_rate: 3.9,
    exposed_thickness_nm: null,
    blank_thickness_nm: null,
    percent_development: null,
    status: 'STOPPED',
    end_reason: null,
  },
  settings: { target_dose: 8 },
  metadata: {},
  end_metadata: null,
  tags: {},
  resources: [],
  snapshots: [{
    snapshot_id: snapshotId,
    format: 'euv_hdf5',
    waveform: {
      name: `snap_${snapshotId}.h5`,
      resource_type: 'euv_snapshot',
      size_bytes: 4096,
      available: true,
      downloadable: true,
      error: null,
    },
    metadata: null,
    final_sequence: 249,
  }],
  metrics: {
    measurements: [],
    exposed_average_nm: null,
    blank_average_nm: null,
    percent_development: null,
    degraded: false,
    error: null,
  },
  log_range: { event_id: runId, created_at: 1_700_000_000, ended_at: 1_700_000_002, complete: true },
  issues: [],
} satisfies ExperimentDetail

const runSeries = {
  schema_version: '3',
  run_id: runId,
  status: 'complete',
  points: [
    { wall_elapsed_seconds: 0, runtime_seconds: 0, dose_increment_mj_cm2: 0, cumulative_dose_mj_cm2: 0, dose_rate_mj_cm2_s: 0, source_index: 0, source_sequence: 0, represented_pulse_count: 1 },
    { wall_elapsed_seconds: 1, runtime_seconds: 1, dose_increment_mj_cm2: 3.8, cumulative_dose_mj_cm2: 3.8, dose_rate_mj_cm2_s: 3.8, source_index: 0, source_sequence: 124, represented_pulse_count: 125 },
    { wall_elapsed_seconds: 2, runtime_seconds: 2, dose_increment_mj_cm2: 4, cumulative_dose_mj_cm2: 7.8, dose_rate_mj_cm2_s: 4, source_index: 0, source_sequence: 249, represented_pulse_count: 125 },
  ],
  errors: [],
  source: 'persisted',
  resolution: 'full',
  raw_pulse_count: 250,
  runtime_basis: 'laser_transmitting',
  time_mode: 'runtime',
  annotations: [],
  issues: [],
  source_kind: 'red_pitaya',
  source_id: 'red-pitaya',
} satisfies RunDoseSeries

const comparison = {
  schema_version: '1',
  run_id: runId,
  status: 'complete',
  series: [
    {
      session_id: '8f202cd8-5f27-42ad-8d91-f70df14393c4',
      source_kind: 'siglent',
      source_id: 'scope-1',
      algorithm: 'captured',
      algorithm_version: 'siglent-captured-v1-native-integral-sum',
      status: 'complete',
      points: [
        { wall_elapsed_seconds: 0.1, dose_increment_mj_cm2: 0, cumulative_dose_mj_cm2: 0, source_sequence: null, represented_pulse_count: 0 },
        { wall_elapsed_seconds: 2.1, dose_increment_mj_cm2: 7.6, cumulative_dose_mj_cm2: 7.6, source_sequence: 249, represented_pulse_count: 250 },
      ],
      raw_point_count: 2,
      pulse_count: 250,
      transfer_count: 1,
      total_dose_mj_cm2: 7.6,
      average_pulse_dose_mj_cm2: 0.0304,
      calibration_profile_id: 'ec84fb5c-2078-430c-8cb1-98c903aaea15',
      calibration_revision: 2,
      calibration_name: 'Siglent scope-1',
      calibration_hash: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
      completeness: { snapshot_count: 1, included_snapshot_count: 1, excluded_snapshot_count: 0, unknown_eligibility_snapshot_count: 0, unknown_step_mode_snapshot_count: 0 },
      issues: [],
    },
    {
      session_id: '8f202cd8-5f27-42ad-8d91-f70df14393c4',
      source_kind: 'siglent',
      source_id: 'scope-1',
      algorithm: 'legacy_compensated',
      algorithm_version: 'legacy-siglent-v1-gap-compensated',
      status: 'incomplete',
      points: [
        { wall_elapsed_seconds: 0.1, dose_increment_mj_cm2: 0, cumulative_dose_mj_cm2: 0, source_sequence: null, represented_pulse_count: 0 },
        { wall_elapsed_seconds: 2.1, dose_increment_mj_cm2: 7.9, cumulative_dose_mj_cm2: 7.9, source_sequence: 249, represented_pulse_count: 250 },
      ],
      raw_point_count: 2,
      pulse_count: 250,
      transfer_count: 1,
      total_dose_mj_cm2: 7.9,
      average_pulse_dose_mj_cm2: 0.0316,
      calibration_profile_id: '00000000-0000-0000-0000-000000000001',
      calibration_revision: 1,
      calibration_name: 'Historical Siglent constants',
      calibration_hash: 'abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789',
      completeness: { snapshot_count: 1, included_snapshot_count: 1, excluded_snapshot_count: 0, unknown_eligibility_snapshot_count: 1, unknown_step_mode_snapshot_count: 1 },
      issues: ['Transfer timing is incomplete.'],
    },
  ],
  errors: [],
  resolution: 'full',
  wall_origin_quality: 'run_preinit',
} satisfies ObserverDoseComparison

const snapshotSeries = {
  schema_version: '2',
  snapshot_id: snapshotId,
  series: 'voltage',
  x_label: 'Wall elapsed time (s)',
  y_label: 'Voltage (V)',
  x: [0, 0.5, 1],
  y: [0, -0.2, 0],
  point_count: 3,
  rolling_window: 1,
  annotations: [],
  issues: [],
} satisfies SnapshotGraphSeries

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    let body: object
    if (path === '/api/v1/live') body = { schema_version: '1' }
    else if (path === `/api/v1/experiments/${runId}`) body = detail
    else if (path.endsWith('/observer-dose-series')) body = comparison
    else if (path.endsWith('/dose-series')) body = runSeries
    else if (path.endsWith('/analysis')) body = {
      schema_version: '1', average_pulse_dose_mj_cm2: 0.03, total_dose_mj_cm2: 7.8,
      delivered_dose_rate_mj_cm2_s: 3.9, pulse_span_seconds: 2, wall_duration_seconds: 2,
      effective_duration_seconds: 2, runtime_contribution_seconds: 2, is_step_exposure: false,
      step_mode_source: 'native', metadata_backfilled: false, backfill_error: null,
    }
    else if (path.includes('/series/')) body = snapshotSeries
    else return route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Not found"}' })
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
})

test('comparison remains usable at desktop and mobile widths', async ({ page }, testInfo) => {
  await page.goto(`/experiments/${runId}`)
  await page.getByRole('button', { name: 'Snapshots' }).click()
  await expect(page.getByRole('heading', { name: 'Primary and observer dose' })).toBeVisible()
  await expect(page.getByText('Siglent scope-1 r2')).toBeVisible()
  await expect(page.getByText('Historical Siglent constants r1')).toBeVisible()
  await expect(page.locator('.dose-comparison-chart canvas')).toHaveCount(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true)
  await page.screenshot({ path: `test-results/observer-comparison-${testInfo.project.name}.png`, fullPage: true })
})