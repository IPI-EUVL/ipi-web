import type { CamerasResponse, LiveResponse } from './types'

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

type SupportedSchemaVersion = '1' | '2' | '3'

export function parseVersionedResponse<T extends { schema_version: SupportedSchemaVersion }>(
  value: unknown,
  supportedVersions: readonly SupportedSchemaVersion[] = ['1'],
): T {
  if (typeof value !== 'object' || value === null || !('schema_version' in value)) {
    throw new Error('The API returned an invalid response.')
  }
  if (!supportedVersions.includes(value.schema_version as SupportedSchemaVersion)) {
    throw new Error(`Unsupported API schema version: ${String(value.schema_version)}`)
  }
  return value as T
}

export async function getJson<T extends { schema_version: SupportedSchemaVersion }>(
  path: string,
  signal?: AbortSignal,
  supportedVersions: readonly SupportedSchemaVersion[] = ['1'],
): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: 'application/json' },
    signal,
  })
  if (!response.ok) {
    let message = `Request failed with status ${response.status}.`
    try {
      const body = (await response.json()) as { detail?: string }
      if (body.detail) message = body.detail
    } catch {
      // Keep the status-based message when an upstream returns a non-JSON error.
    }
    throw new ApiError(message, response.status)
  }
  return parseVersionedResponse<T>(await response.json(), supportedVersions)
}

export async function postJson<T extends { schema_version: SupportedSchemaVersion }>(
  path: string,
  signal?: AbortSignal,
  supportedVersions: readonly SupportedSchemaVersion[] = ['1'],
): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { Accept: 'application/json' },
    signal,
  })
  if (!response.ok) {
    let message = `Request failed with status ${response.status}.`
    try {
      const body = (await response.json()) as { detail?: string }
      if (body.detail) message = body.detail
    } catch {
      // Keep the status-based message when an upstream returns a non-JSON error.
    }
    throw new ApiError(message, response.status)
  }
  return parseVersionedResponse<T>(await response.json(), supportedVersions)
}

export function fetchLive(signal?: AbortSignal): Promise<LiveResponse> {
  return getJson<LiveResponse>('/api/v1/live', signal)
}

export function fetchCameras(signal?: AbortSignal): Promise<CamerasResponse> {
  return getJson<CamerasResponse>('/api/v1/cameras', signal)
}