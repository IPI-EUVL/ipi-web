import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError, fetchLive, parseVersionedResponse } from './client'
import { LIVE_QUERY_KEY, type LiveConnectionState, type LiveResponse } from './types'

type EventStreamCallbacks = {
  onSnapshot: (snapshot: LiveResponse) => void
  onState: (state: LiveConnectionState) => void
  onError: (error: Error | null) => void
}

type EventStreamFactory = (url: string) => EventSource

export function connectLiveEvents(
  callbacks: EventStreamCallbacks,
  createEventSource: EventStreamFactory = (url) => new EventSource(url),
): () => void {
  const source = createEventSource('/api/v1/live/events')
  source.onopen = () => {
    callbacks.onError(null)
    callbacks.onState('live')
  }
  source.onerror = () => {
    callbacks.onState(source.readyState === EventSource.CLOSED ? 'offline' : 'reconnecting')
  }
  source.addEventListener('live', (event) => {
    try {
      const snapshot = parseVersionedResponse<LiveResponse>(JSON.parse(event.data))
      callbacks.onSnapshot(snapshot)
      callbacks.onError(null)
      callbacks.onState('live')
    } catch (error) {
      callbacks.onError(error instanceof Error ? error : new Error('The live update could not be read.'))
      callbacks.onState('offline')
      source.close()
    }
  })
  return () => source.close()
}

export function useLiveSnapshot() {
  const queryClient = useQueryClient()
  const [streamState, setStreamState] = useState<LiveConnectionState>('connecting')
  const [streamError, setStreamError] = useState<Error | null>(null)
  const [lastEventAt, setLastEventAt] = useState<number | null>(null)
  const query = useQuery({
    queryKey: LIVE_QUERY_KEY,
    queryFn: ({ signal }) => fetchLive(signal),
    staleTime: Number.POSITIVE_INFINITY,
    refetchOnWindowFocus: false,
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.status === 503) return failureCount < 20
      return failureCount < 3
    },
    retryDelay: (attempt) => Math.min(500 * 2 ** attempt, 3000),
  })

  useEffect(() => connectLiveEvents({
    onSnapshot: (snapshot) => {
      queryClient.setQueryData(LIVE_QUERY_KEY, snapshot)
      setLastEventAt(Date.now())
    },
    onState: setStreamState,
    onError: setStreamError,
  }), [queryClient])

  const connectionState = streamState === 'reconnecting' && !query.data ? 'offline' : streamState
  return {
    snapshot: query.data,
    connectionState,
    error: streamError ?? query.error,
    isLoading: query.isPending,
    lastEventAt,
  }
}