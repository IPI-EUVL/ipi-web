import { describe, expect, it, vi } from 'vitest'

import { connectLiveEvents } from './live'
import { makeLiveSnapshot } from '../test/fixtures'

class FakeEventSource {
  static readonly CLOSED = 2
  onopen: ((event: Event) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  readyState = 0
  closed = false
  private liveListener: ((event: MessageEvent<string>) => void) | null = null

  addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
    if (type === 'live') this.liveListener = listener as (event: MessageEvent<string>) => void
  }

  close() {
    this.closed = true
    this.readyState = FakeEventSource.CLOSED
  }

  emitOpen() {
    this.readyState = 1
    this.onopen?.(new Event('open'))
  }

  emitLive(value: unknown) {
    this.liveListener?.(new MessageEvent('live', { data: JSON.stringify(value) }))
  }
}

describe('live event stream', () => {
  it('publishes valid snapshots and closes cleanly', () => {
    const stream = new FakeEventSource()
    const onSnapshot = vi.fn()
    const onState = vi.fn()
    const close = connectLiveEvents(
      { onSnapshot, onState, onError: vi.fn() },
      () => stream as unknown as EventSource,
    )

    stream.emitOpen()
    stream.emitLive(makeLiveSnapshot())
    close()

    expect(onState).toHaveBeenCalledWith('live')
    expect(onSnapshot).toHaveBeenCalledOnce()
    expect(stream.closed).toBe(true)
  })

  it('rejects unsupported schema versions and stops reconnecting', () => {
    const stream = new FakeEventSource()
    const onError = vi.fn()
    const onState = vi.fn()
    connectLiveEvents(
      { onSnapshot: vi.fn(), onState, onError },
      () => stream as unknown as EventSource,
    )

    stream.emitLive({ ...makeLiveSnapshot(), schema_version: '2' })

    expect(onError).toHaveBeenCalledOnce()
    expect(onState).toHaveBeenLastCalledWith('offline')
    expect(stream.closed).toBe(true)
  })
})