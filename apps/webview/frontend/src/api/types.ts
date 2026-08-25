import type { components } from './types.generated'

export type LiveResponse = components['schemas']['LiveResponse']
export type CamerasResponse = components['schemas']['CamerasResponse']
export type ExperimentDetails = components['schemas']['ExperimentDetails']
export type ProgressSummary = components['schemas']['ProgressSummary']
export type BatchExposure = components['schemas']['BatchExposureSummary']
export type BatchSlot = components['schemas']['BatchSlotSummary']
export type SubsystemSummary = components['schemas']['SubsystemSummary']
export type SourceSummary = components['schemas']['SourceSummary']
export type HealthState = components['schemas']['HealthState']
export type PublicExperimentPhase = components['schemas']['PublicExperimentPhase']
export type SourceState = components['schemas']['SourceState']

export type LiveConnectionState = 'connecting' | 'live' | 'reconnecting' | 'offline'

export const LIVE_QUERY_KEY = ['live'] as const
export const CAMERAS_QUERY_KEY = ['cameras'] as const