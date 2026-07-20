import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiUtterance } from '../types/api'
import { queryKeys } from './keys'
import { useDeleteUtteranceMutation } from './sessions'

const { mockDeleteUtterance } = vi.hoisted(() => ({
  mockDeleteUtterance: vi.fn(),
}))

vi.mock('../api/sessions', async () => {
  const actual = await vi.importActual('../api/sessions')
  return { ...actual, deleteUtterance: mockDeleteUtterance }
})

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

function makeApiUtterance(id: string): ApiUtterance {
  return {
    id,
    session_id: 'session-1',
    started_ms: id === 'utt-1' ? 1000 : 2000,
    ended_ms: id === 'utt-1' ? 1500 : 2500,
    transcript: id,
    language: 'EN',
    confidence: 0.9,
    speaker_segment_id: null,
    speaker_contact_id: null,
    source: 'mic',
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('useDeleteUtteranceMutation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('optimistically removes the raw API utterance and restores it on failure', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    const queryKey = queryKeys.sessions.utterances('session-1')
    const original = [makeApiUtterance('utt-1'), makeApiUtterance('utt-2')]
    queryClient.setQueryData(queryKey, original)
    const request = deferred<void>()
    mockDeleteUtterance.mockReturnValueOnce(request.promise)

    const { result } = renderHook(
      () => useDeleteUtteranceMutation('session-1'),
      { wrapper: createWrapper(queryClient) },
    )
    const deletion = result.current.mutateAsync('utt-1')

    await waitFor(() => {
      expect(queryClient.getQueryData(queryKey)).toEqual([original[1]])
    })
    request.reject(new Error('delete failed'))
    await expect(deletion).rejects.toThrow('delete failed')
    expect(queryClient.getQueryData(queryKey)).toEqual(original)
  })

  it('keeps the deleted utterance absent after a successful request', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    const queryKey = queryKeys.sessions.utterances('session-1')
    const original = [makeApiUtterance('utt-1'), makeApiUtterance('utt-2')]
    queryClient.setQueryData(queryKey, original)
    mockDeleteUtterance.mockResolvedValueOnce(undefined)

    const { result } = renderHook(
      () => useDeleteUtteranceMutation('session-1'),
      { wrapper: createWrapper(queryClient) },
    )

    const deletion = result.current.mutateAsync('utt-2')
    await act(async () => { await deletion })
    expect(queryClient.getQueryData(queryKey)).toEqual([original[0]])
    expect(mockDeleteUtterance).toHaveBeenCalledWith('utt-2')
  })
})
