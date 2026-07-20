import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Utterance } from '../types/domain'
import { CurrentSession } from './CurrentSession'

const { mockMutateAsync, mockAddToast } = vi.hoisted(() => ({
  mockMutateAsync: vi.fn(),
  mockAddToast: vi.fn(),
}))

vi.mock('../query/contacts', () => ({
  useContactsData: () => ({ contacts: [], contactById: () => null }),
}))

vi.mock('../query/sessions', () => ({
  useDeleteUtteranceMutation: () => ({ mutateAsync: mockMutateAsync }),
}))

vi.mock('./Toast/useToast', () => ({
  useToast: () => ({ addToast: mockAddToast }),
}))

vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count, getItemKey }: { count: number; getItemKey?: (index: number) => string }) => ({
    getTotalSize: () => count * 120,
    getVirtualItems: () => Array.from({ length: count }, (_, index) => ({
      key: getItemKey?.(index) ?? index,
      index,
      start: index * 120,
    })),
    measureElement: () => undefined,
    measure: () => undefined,
    scrollToIndex: () => undefined,
  }),
}))

function makeUtterance(id: string, text: string, startedMs: number): Utterance {
  return {
    id,
    speakerId: null,
    speakerSegmentId: `segment-${id}`,
    time: `0:0${startedMs / 1000}`,
    text,
    startedMs,
    endedMs: startedMs + 1000,
  }
}

function Harness({ initial }: { initial: Utterance[] }) {
  const [utterances, setUtterances] = useState(initial)
  return (
    <CurrentSession
      setRecording={() => undefined}
      utterances={utterances}
      setUtterances={setUtterances}
    />
  )
}

function renderSession(initial: Utterance[]) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <Harness initial={initial} />
    </QueryClientProvider>,
  )
}

describe('CurrentSession utterance deletion', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockMutateAsync.mockResolvedValue(undefined)
  })

  it('removes the selected persisted row immediately without leaving later rows behind a gap', async () => {
    renderSession([
      makeUtterance('utt-1', 'first', 1000),
      makeUtterance('utt-2', 'middle', 2000),
      makeUtterance('utt-3', 'last', 3000),
    ])

    fireEvent.click(screen.getByTestId('delete-utt-utt-2'))

    expect(screen.queryByTestId('utterance-utt-2')).toBeNull()
    expect(screen.getByTestId('utterance-utt-1')).toHaveTextContent('first')
    expect(screen.getByTestId('utterance-utt-3')).toHaveTextContent('last')
    await waitFor(() => expect(mockMutateAsync).toHaveBeenCalledWith('utt-2'))
  })

  it('restores the deleted row when persistence fails and shows an error', async () => {
    mockMutateAsync.mockRejectedValueOnce(new Error('delete failed'))
    renderSession([
      makeUtterance('utt-1', 'first', 1000),
      makeUtterance('utt-2', 'middle', 2000),
      makeUtterance('utt-3', 'last', 3000),
    ])

    fireEvent.click(screen.getByTestId('delete-utt-utt-2'))
    expect(screen.queryByTestId('utterance-utt-2')).toBeNull()

    await waitFor(() => {
      expect(screen.getByTestId('utterance-utt-2')).toHaveTextContent('middle')
    })
    expect(mockAddToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' }))
  })
})
