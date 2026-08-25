import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { LogsPage } from './LogsPage'

function stubBrowserApis() {
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }))
  vi.stubGlobal('IntersectionObserver', class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
}

function renderLogsPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<MantineProvider><QueryClientProvider client={client}><LogsPage /></QueryClientProvider></MantineProvider>)
}

describe('LogsPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows one page-level error when the log service is unavailable', async () => {
    stubBrowserApis()
    const fetchMock = vi.fn(async () => new Response(
      JSON.stringify({ detail: 'Log browser is not configured.' }),
      { status: 503, headers: { 'Content-Type': 'application/json' } },
    ))
    vi.stubGlobal('fetch', fetchMock)
    renderLogsPage()

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Log browser unavailable' })).toBeInTheDocument())

    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.getByText(/IPI_ECS_LOG_DIR/)).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalled()
  })

  it('retracts drawers and filters by the selected record UUID', async () => {
    stubBrowserApis()
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/archives')) return new Response(JSON.stringify({ schema_version: '1', items: [{ name: 'current', is_current: true, start_line: 0, end_line_exclusive: 8, start_timestamp: null, end_timestamp: null }] }))
      if (url.includes('/events')) return new Response(JSON.stringify({
        schema_version: '1',
        items: [{
          event_id: 'event-7', e_type: 'RUN', level: 'INFO', message: 'Exposure selected',
          start_line: 7, end_line: 7, start_timestamp: null, end_timestamp: null,
          data_start: {}, data_end: {},
        }],
      }))
      return new Response(JSON.stringify({
        schema_version: '1',
        archive: 'current',
        filters: { origin_uuid: null, l_type: null, level: null, min_level: null, exclude_types: null, line_from: null, line_to: null, since: null, until: null },
        rows: [{ line: 7, timestamp: null, origin_uuid: 'source-uuid', l_type: 'EXP', level: 'INFO', subsystem: 'Target', message: 'Exposure started', record: { origin: { uuid: 'source-uuid' } } }],
        first_line: 7,
        last_line: 7,
        has_before: false,
        has_after: false,
        at_tail: true,
      }))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderLogsPage()

    await screen.findByRole('button', { name: 'View raw record 7' })
    fireEvent.click(screen.getByRole('button', { name: /RUN · INFO/ }))
    await waitFor(() => {
      const eventRequest = fetchMock.mock.calls.map(([input]) => String(input))
        .find((url) => url.includes('direction=after') && url.includes('anchor_line=6'))
      expect(eventRequest).toBeDefined()
      expect(eventRequest).not.toContain('line_from=')
      expect(eventRequest).not.toContain('line_to=')
    })
    fireEvent.click(screen.getByRole('button', { name: 'Clear event' }))
    await waitFor(() => {
      const entryCalls = fetchMock.mock.calls.map(([input]) => String(input)).filter((url) => url.includes('/entries'))
      expect(entryCalls.at(-1)).toContain('direction=tail')
      expect(entryCalls.at(-1)).not.toContain('anchor_line=6')
    })
    fireEvent.click(screen.getByRole('button', { name: 'Hide archives and filters' }))
    fireEvent.click(screen.getByRole('button', { name: 'Hide event markers' }))
    expect(screen.queryByLabelText('Log archive and filters')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Indexed events')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'View raw record 7' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Filter by UUID' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes('origin_uuid=source-uuid'))).toBe(true))
  })
})