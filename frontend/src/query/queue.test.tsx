import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { UnknownQueueItem, Utterance } from '../types/domain'
import { queryKeys } from './keys'
import {
  useDeleteQueueClusterMutation,
  useResolveQueueClusterMutation,
  useSkipQueueClusterMutation,
} from './queue'

const {
  mockDeleteQueueCluster,
  mockResolveQueueCluster,
  mockSkipQueueCluster,
} = vi.hoisted(() => ({
  mockDeleteQueueCluster: vi.fn(),
  mockResolveQueueCluster: vi.fn(),
  mockSkipQueueCluster: vi.fn(),
}))

vi.mock('../api/queue', async () => {
  const actual = await vi.importActual('../api/queue')
  return {
    ...actual,
    deleteQueueCluster: mockDeleteQueueCluster,
    resolveQueueCluster: mockResolveQueueCluster,
    skipQueueCluster: mockSkipQueueCluster,
  }
})

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function makeCluster(overrides: Partial<UnknownQueueItem> = {}): UnknownQueueItem {
  return {
    id: 'cluster-1',
    queueIds: ['queue-1', 'queue-2'],
    segmentIds: ['segment-1', 'segment-2'],
    sessionIds: ['session-1'],
    sessionTitles: ['Planning'],
    sessionId: 'session-1',
    sessionTitle: 'Planning',
    sessionDate: '2026-06-30',
    label: 'Unknown speaker',
    fragmentCount: 2,
    totalDuration: '0:09',
    quote: 'Need to follow up',
    candidates: [],
    status: 'unresolved',
    ...overrides,
  }
}

function makeUtterance(overrides: Partial<Utterance> = {}): Utterance {
  return {
    id: 'utt-1',
    speakerId: null,
    speakerSegmentId: 'segment-1',
    time: '0:01',
    text: 'Need to follow up',
    ...overrides,
  }
}

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

function createClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
}

describe('queue mutations', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('optimistically resolves a queue cluster and patches matching session utterances', async () => {
    const queryClient = createClient()
    const cluster = makeCluster()
    const otherCluster = makeCluster({ id: 'cluster-2', queueIds: ['queue-3'], segmentIds: ['segment-3'] })
    const untouchedUtterance = makeUtterance({
      id: 'utt-2',
      speakerSegmentId: 'segment-x',
      speakerId: null,
    })
    const targetUtterance = makeUtterance()
    const api = deferred<{ resolved_count: number }>()
    mockResolveQueueCluster.mockReturnValue(api.promise)

    queryClient.setQueryData(queryKeys.queue.list({ limit: 20, offset: 0 }), [cluster, otherCluster])
    queryClient.setQueryData(queryKeys.queue.list({ limit: 20, offset: 20 }), [cluster])
    queryClient.setQueryData(queryKeys.sessions.utterances('session-1'), [
      targetUtterance,
      untouchedUtterance,
    ])

    const { result } = renderHook(
      () => useResolveQueueClusterMutation(),
      { wrapper: createWrapper(queryClient) },
    )

    const mutation = act(() =>
      result.current.mutateAsync({ cluster, contactId: 'contact-1' }),
    )

    await waitFor(() => {
      expect(queryClient.getQueryData(queryKeys.queue.list({ limit: 20, offset: 0 }))).toEqual([otherCluster])
    })
    expect(queryClient.getQueryData(queryKeys.queue.list({ limit: 20, offset: 20 }))).toEqual([])
    expect(queryClient.getQueryData<Utterance[]>(queryKeys.sessions.utterances('session-1'))).toEqual([
      { ...targetUtterance, speakerId: 'contact-1' },
      untouchedUtterance,
    ])
    expect(mockResolveQueueCluster).toHaveBeenCalledWith(['queue-1', 'queue-2'], 'contact-1')

    api.resolve({ resolved_count: 2 })
    await mutation
  })

  it('restores queue and utterance caches and calls live rollback when resolve fails', async () => {
    const queryClient = createClient()
    const cluster = makeCluster()
    const originalQueue = [cluster]
    const filteredQueue = [cluster]
    const originalUtterances = [makeUtterance()]
    const rollbackLive = vi.fn()
    const applyLiveResolution = vi.fn(() => rollbackLive)
    const api = deferred<{ resolved_count: number }>()
    mockResolveQueueCluster.mockReturnValue(api.promise)

    queryClient.setQueryData(queryKeys.queue.list({ limit: 20, offset: 0 }), originalQueue)
    queryClient.setQueryData(queryKeys.queue.list({ limit: 20, offset: 0, q: 'follow' }), filteredQueue)
    queryClient.setQueryData(queryKeys.sessions.utterances('session-1'), originalUtterances)

    const { result } = renderHook(
      () => useResolveQueueClusterMutation({ onApplyLiveResolution: applyLiveResolution }),
      { wrapper: createWrapper(queryClient) },
    )

    const mutation = act(() =>
      result.current.mutateAsync({ cluster, contactId: 'contact-1' }),
    )

    await waitFor(() => {
      expect(queryClient.getQueryData(queryKeys.queue.list({ limit: 20, offset: 0 }))).toEqual([])
    })
    expect(queryClient.getQueryData(queryKeys.queue.list({ limit: 20, offset: 0, q: 'follow' }))).toEqual([])

    api.reject(new Error('resolve failed'))
    await expect(mutation).rejects.toThrow('resolve failed')

    expect(queryClient.getQueryData(queryKeys.queue.list({ limit: 20, offset: 0 }))).toEqual(originalQueue)
    expect(queryClient.getQueryData(queryKeys.queue.list({ limit: 20, offset: 0, q: 'follow' }))).toEqual(filteredQueue)
    expect(queryClient.getQueryData(queryKeys.sessions.utterances('session-1'))).toEqual(originalUtterances)
    expect(applyLiveResolution).toHaveBeenCalledWith(['segment-1', 'segment-2'], 'contact-1')
    expect(rollbackLive).toHaveBeenCalledOnce()
  })

  it('restores a skipped cluster when the skip request fails', async () => {
    const queryClient = createClient()
    const cluster = makeCluster()
    const api = deferred<{ skipped_count: number }>()
    mockSkipQueueCluster.mockReturnValue(api.promise)
    queryClient.setQueryData(queryKeys.queue.list({ limit: 20, offset: 0 }), [cluster])
    queryClient.setQueryData(queryKeys.queue.list({ limit: 20, offset: 0, sessionId: 'session-1' }), [cluster])

    const { result } = renderHook(
      () => useSkipQueueClusterMutation(),
      { wrapper: createWrapper(queryClient) },
    )

    const mutation = act(() => result.current.mutateAsync({ cluster }))

    await waitFor(() => {
      expect(queryClient.getQueryData(queryKeys.queue.list({ limit: 20, offset: 0 }))).toEqual([])
    })
    expect(queryClient.getQueryData(queryKeys.queue.list({ limit: 20, offset: 0, sessionId: 'session-1' }))).toEqual([])

    api.reject(new Error('skip failed'))
    await expect(mutation).rejects.toThrow('skip failed')

    expect(queryClient.getQueryData(queryKeys.queue.list({ limit: 20, offset: 0 }))).toEqual([cluster])
    expect(queryClient.getQueryData(queryKeys.queue.list({ limit: 20, offset: 0, sessionId: 'session-1' }))).toEqual([cluster])
    expect(mockSkipQueueCluster).toHaveBeenCalledWith(['queue-1', 'queue-2'])
  })

  it('restores a deleted cluster when the delete request fails', async () => {
    const queryClient = createClient()
    const cluster = makeCluster()
    const api = deferred<{ deleted_count: number }>()
    mockDeleteQueueCluster.mockReturnValue(api.promise)
    queryClient.setQueryData(queryKeys.queue.list({ limit: 20, offset: 0 }), [cluster])
    queryClient.setQueryData(queryKeys.queue.list({ limit: 20, offset: 20 }), [cluster])

    const { result } = renderHook(
      () => useDeleteQueueClusterMutation(),
      { wrapper: createWrapper(queryClient) },
    )

    const mutation = act(() => result.current.mutateAsync({ cluster }))

    await waitFor(() => {
      expect(queryClient.getQueryData(queryKeys.queue.list({ limit: 20, offset: 0 }))).toEqual([])
    })
    expect(queryClient.getQueryData(queryKeys.queue.list({ limit: 20, offset: 20 }))).toEqual([])

    api.reject(new Error('delete failed'))
    await expect(mutation).rejects.toThrow('delete failed')

    expect(queryClient.getQueryData(queryKeys.queue.list({ limit: 20, offset: 0 }))).toEqual([cluster])
    expect(queryClient.getQueryData(queryKeys.queue.list({ limit: 20, offset: 20 }))).toEqual([cluster])
    expect(mockDeleteQueueCluster).toHaveBeenCalledWith(['queue-1', 'queue-2'])
  })
})
