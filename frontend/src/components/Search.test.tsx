import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Search } from './Search'
import type { ApiSearchResponse } from '../types/api'
import type { ApiSearchHit } from '../types/api'

const { mockSearchResults } = vi.hoisted(() => {
  const hits: ApiSearchHit[] = [
    {
      utterance_id: 'u1',
      session_id: 's1',
      session_title: 'Team Sync',
      transcript: 'We need to review the architecture',
      snippet: 'We need to <b>review</b> the architecture',
      started_ms: 5000,
      language: 'EN',
    },
    {
      utterance_id: 'u2',
      session_id: 's1',
      session_title: 'Team Sync',
      transcript: 'Review the PR please',
      snippet: '<b>Review</b> the PR please',
      started_ms: 15000,
      language: 'EN',
    },
    {
      utterance_id: 'u3',
      session_id: 's2',
      session_title: 'Planning',
      transcript: 'Плануємо спринт',
      snippet: 'Плануємо спринт',
      started_ms: 3000,
      language: 'UK',
    },
  ]
  return {
    mockSearchResults: (_q: string, _opts?: { language?: string }): ApiSearchResponse => {
      let filtered = [...hits]
      if (_opts?.language) {
        filtered = filtered.filter(
          (h) => h.language === _opts.language,
        )
      }
      return { query: _q, hits: filtered, total: filtered.length }
    },
  }
})

vi.mock('../api/search', () => ({
  searchUtterances: (q: string, opts?: { language?: string }) =>
    Promise.resolve(mockSearchResults(q, opts)),
}))

function renderWithProviders() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <Search />
    </QueryClientProvider>,
  )
}

describe('Search', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders search input', () => {
    renderWithProviders()
    expect(screen.getByTestId('search-input')).toBeDefined()
  })

  it('renders language filter buttons', () => {
    renderWithProviders()
    expect(screen.getByTestId('lang-filter-uk')).toBeDefined()
    expect(screen.getByTestId('lang-filter-en')).toBeDefined()
  })

  it('shows empty hint when no query', () => {
    renderWithProviders()
    expect(screen.queryByTestId(/search-group-/)).toBeNull()
  })

  it('filters by language', async () => {
    renderWithProviders()

    fireEvent.change(screen.getByTestId('search-input'), {
      target: { value: 'review' },
    })

    await waitFor(() => {
      expect(screen.getByTestId('search-group-s1')).toBeDefined()
    })

    fireEvent.click(screen.getByTestId('lang-filter-uk'))

    // After filtering to UK only, s1 results (EN) should disappear
    await waitFor(() => {
      expect(screen.getByTestId('search-group-s2')).toBeDefined()
      expect(screen.queryByTestId('search-group-s1')).toBeNull()
    })
  })

  it('clears query when clear button is clicked', async () => {
    renderWithProviders()

    fireEvent.change(screen.getByTestId('search-input'), {
      target: { value: 'test' },
    })

    await waitFor(() => {
      const clearBtn = screen.queryByText('✕')
      if (clearBtn) fireEvent.click(clearBtn)
    })

    await waitFor(() => {
      const input = screen.getByTestId('search-input') as HTMLInputElement
      expect(input.value).toBe('')
    })
  })
})
