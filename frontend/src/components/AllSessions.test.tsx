import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AllSessions } from './AllSessions'

vi.mock('../api/sessions', async () => {
  const actual = await vi.importActual('../api/sessions')
  return {
    ...actual,
    listSessions: vi.fn().mockResolvedValue([
      { id: 's1', title: '', started_at: '2026-04-29T10:00:00Z', ended_at: '2026-04-29T10:30:00Z', notes: '', language_hint: null, utterance_count: 3, speakers: [] },
      { id: 's2', title: 'Design review', started_at: '2026-04-28T14:00:00Z', ended_at: '2026-04-28T14:45:00Z', notes: '', language_hint: null, utterance_count: 5, speakers: ['c1'] },
    ]),
    updateSession: vi.fn().mockResolvedValue({}),
    listUtterances: vi.fn().mockResolvedValue([]),
  }
})

vi.mock('../api/contacts', async () => {
  const actual = await vi.importActual('../api/contacts')
  return { ...actual, listContacts: vi.fn().mockResolvedValue([]) }
})

function renderWithProviders() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AllSessions />
    </QueryClientProvider>,
  )
}

const UNTITLED = 'Без назви'

describe('AllSessions inline rename', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
    expect(screen.getByText('Design review')).toBeDefined()
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
    // Second occurrence is the transcript panel title
    const panelTitle = screen.getAllByText(UNTITLED)[1]
    const parent = panelTitle.closest('[style*="cursor: pointer"]')
    expect(parent).not.toBeNull()
  })

  it('session list shows count badge', async () => {
    renderWithProviders()
    await waitForLoaded()
    expect(screen.getByText('2')).toBeDefined()
  })
})
