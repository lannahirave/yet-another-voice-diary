import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AllSessions } from './AllSessions'

const { mockListUtterances } = vi.hoisted(() => ({
  mockListUtterances: vi.fn(),
}))

const sessions = [
  {
    id: 'session-1',
    title: 'First session',
    started_at: '2026-07-19T10:00:00Z',
    ended_at: '2026-07-19T10:30:00Z',
    notes: '',
    language_hint: 'EN',
    utterance_count: 2,
    speakers: [],
  },
  {
    id: 'session-2',
    title: 'Selected session',
    started_at: '2026-07-18T10:00:00Z',
    ended_at: '2026-07-18T10:30:00Z',
    notes: '',
    language_hint: 'EN',
    utterance_count: 2,
    speakers: [],
  },
]

function makeUtterance(id: string, transcript: string, startedMs: number) {
  return {
    id,
    session_id: 'session-2',
    started_ms: startedMs,
    ended_ms: startedMs + 1000,
    transcript,
    language: 'EN',
    confidence: 0.9,
    speaker_segment_id: null,
    speaker_contact_id: null,
    source: 'mic',
  }
}

vi.mock('../api/sessions', () => ({
  listSessions: vi.fn(() => Promise.resolve(sessions)),
  listUtterances: (sessionId: string, offset = 0, limit = 50) =>
    mockListUtterances(sessionId, offset, limit),
  updateSession: vi.fn(),
  deleteUtterance: vi.fn(),
}))

vi.mock('../api/contacts', () => ({
  listContacts: vi.fn(() => Promise.resolve([])),
}))

function renderWithProviders() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AllSessions />
    </QueryClientProvider>,
  )
}

describe('AllSessions transcript pagination', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockListUtterances.mockImplementation((sessionId: string, offset: number, limit: number) => {
      if (sessionId === 'session-1') {
        return Promise.resolve([makeUtterance('first-1', 'First session transcript', 1000)])
      }
      if (offset === 0) {
        return Promise.resolve([
          makeUtterance('selected-1', 'Loaded first page', 1000),
          ...Array.from({ length: Math.max(0, limit - 1) }, (_, index) =>
            makeUtterance(`selected-padding-${index}`, `Padding ${index}`, 1100 + index)),
        ])
      }
      return Promise.resolve([makeUtterance('selected-2', 'Loaded next page', 2000)])
    })
  })

  it('loads the next transcript page after selecting a session', async () => {
    renderWithProviders()

    await waitFor(() => expect(screen.getByTestId('session-card-session-2')).toBeDefined())
    fireEvent.click(screen.getByTestId('session-card-session-2'))

    expect(await screen.findByText('Loaded first page')).toBeDefined()
    fireEvent.click(screen.getByTestId('session-load-more'))

    expect(await screen.findByText('Loaded next page')).toBeDefined()
    const calls = mockListUtterances.mock.calls
    const lastCall = calls[calls.length - 1]
    expect(lastCall[0]).toBe('session-2')
    expect(lastCall[1]).toBeGreaterThan(0)
    expect(lastCall[2]).toBeGreaterThan(0)
  })
})
