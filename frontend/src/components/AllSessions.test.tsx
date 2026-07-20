import { describe, expect, it, vi, beforeEach } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AllSessions } from './AllSessions'

const { mockSessions, mockUpdateSession, mockStartRefinement } = vi.hoisted(() => {
  const sessions = [
    { id: 's1', title: '', started_at: '2026-04-29T10:00:00Z', ended_at: '2026-04-29T10:30:00Z', notes: '', language_hint: null, utterance_count: 3, speakers: [], recording_available: true, recording_size_bytes: 32044, refinement_status: null },
    { id: 's2', title: 'Morning check-in', started_at: '2026-04-28T14:00:00Z', ended_at: '2026-04-28T14:45:00Z', notes: '', language_hint: null, utterance_count: 5, speakers: ['c1'] },
  ]
  const updateFn = vi.fn(async (id: string, payload: { title?: string }) => {
    const s = sessions.find((s) => s.id === id)
    if (s && payload.title !== undefined) s.title = payload.title
    return { ...s, ...payload }
  })
  return {
    mockSessions: sessions,
    mockUpdateSession: updateFn,
    mockStartRefinement: vi.fn(async (sessionId: string) => ({
      id: 'job-1', session_id: sessionId, status: 'queued', stage: 'queued',
      progress: 0, current_source: null, processed_items: 0, total_items: 0,
      error: null, cancel_requested: false, created_at: 1, started_at: null, completed_at: null,
    })),
  }
})

vi.mock('../api/sessions', async () => {
  const actual = await vi.importActual('../api/sessions')
  return {
    ...actual,
    listSessions: vi.fn().mockImplementation(() => Promise.resolve([...mockSessions])),
    updateSession: mockUpdateSession,
    listUtterances: vi.fn(() => Promise.resolve([])),
    getRefinement: vi.fn(() => Promise.resolve(null)),
    startRefinement: mockStartRefinement,
  }
})

vi.mock('../api/contacts', async () => {
  const actual = await vi.importActual('../api/contacts')
  return { ...actual, listContacts: vi.fn().mockResolvedValue([]) }
})

function renderWithProviders(ui = <AllSessions />) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  )
}

const UNTITLED = 'Без назви'

describe('AllSessions inline rename', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSessions.length = 0
    mockSessions.push(
      { id: 's1', title: '', started_at: '2026-04-29T10:00:00Z', ended_at: '2026-04-29T10:30:00Z', notes: '', language_hint: null, utterance_count: 3, speakers: [], recording_available: true, recording_size_bytes: 32044, refinement_status: null },
      { id: 's2', title: 'Morning check-in', started_at: '2026-04-28T14:00:00Z', ended_at: '2026-04-28T14:45:00Z', notes: '', language_hint: null, utterance_count: 5, speakers: ['c1'] },
    )
  })

  async function waitForLoaded() {
    await waitFor(() => {
      expect(screen.getAllByText(UNTITLED).length).toBeGreaterThanOrEqual(2)
    })
  }

  it('empty title shows translated placeholder', async () => {
    renderWithProviders()
    await waitForLoaded()
    expect(screen.getAllByText(UNTITLED).length).toBeGreaterThanOrEqual(2)
  })

  it('titled session shows its name', async () => {
    renderWithProviders()
    await waitForLoaded()
    expect(screen.getByText('Morning check-in')).toBeDefined()
  })

  it('empty title has cursor pointer CSS (clickable)', async () => {
    renderWithProviders()
    await waitForLoaded()
    for (const el of screen.getAllByText(UNTITLED)) {
      const parent = el.closest('[style*="cursor: pointer"]')
      expect(parent).not.toBeNull()
    }
  })

  it('transcript panel title also has cursor pointer', async () => {
    renderWithProviders()
    await waitForLoaded()
    const panelTitle = screen.getAllByText(UNTITLED)[1]
    const parent = panelTitle.closest('[style*="cursor: pointer"]')
    expect(parent).not.toBeNull()
  })

  it('session list shows count badge', async () => {
    renderWithProviders()
    await waitForLoaded()
    expect(screen.getByText('2')).toBeDefined()
  })

  it('starts refinement for a retained completed recording', async () => {
    renderWithProviders()
    await waitForLoaded()
    screen.getByTestId('start-refinement').click()
    await waitFor(() => expect(mockStartRefinement).toHaveBeenCalledWith('s1'))
    expect(await screen.findByText('Refinement queued')).toBeDefined()
  })

  it('renamed title persists after remount', async () => {
    const { unmount } = renderWithProviders()
    await waitForLoaded()

    // Simulate rename via mock mutation
    mockSessions[0].title = 'Standup notes'

    // Unmount (simulate switching tab)
    unmount()
    await act(() => new Promise((r) => setTimeout(r, 10)))

    // Remount (simulate returning to tab)
    renderWithProviders()
    await waitFor(() => {
      expect(screen.getByTestId('session-title').textContent).toBe('Standup notes')
    })
  })
})
