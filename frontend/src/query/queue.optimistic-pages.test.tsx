import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiUtterance } from '../types/api'
import type { UnknownQueueItem } from '../types/domain'
import { queryKeys } from './keys'
import { useResolveQueueClusterMutation } from './queue'

const resolveQueueCluster = vi.hoisted(() => vi.fn())
vi.mock('../api/queue', async () => ({
  ...(await vi.importActual('../api/queue')),
  resolveQueueCluster,
}))

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function createClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
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

const resolveInvalidationRoots = [
  queryKeys.queue.all,
  queryKeys.contacts.list(),
  queryKeys.contacts.utterancesRoot(),
  queryKeys.sessions.list(),
  queryKeys.sessions.utterancesRoot(),
] as const

const cluster: UnknownQueueItem = {
  id: 'cluster-1', queueIds: ['q-1'], segmentIds: ['seg-1'], sessionIds: ['s-1'],
  sessionTitles: ['Session'], sessionId: 's-1', sessionTitle: 'Session', sessionDate: '2026-07-20',
  label: 'Unknown speaker', fragmentCount: 1, totalDuration: '0:01', quote: 'hello', candidates: [], status: 'unresolved',
}

const utterance = (id: string, segment: string | null): ApiUtterance => ({
  id, session_id: 's-1', started_ms: 0, ended_ms: 1000, transcript: id, language: 'EN', confidence: 1,
  speaker_segment_id: segment, speaker_contact_id: null, source: 'mic',
})

describe('resolve queue optimistic paginated cache', () => {
  beforeEach(() => { resolveQueueCluster.mockReset() })

  it('patches every matching utterance across pages and preserves null segment IDs', async () => {
    const client = createClient()
    const invalidateQueries = vi.spyOn(client, 'invalidateQueries')
    const queryKey = queryKeys.sessions.utterances('s-1')
    const pages = {
      pages: [
        [utterance('u-1', 'seg-1'), utterance('u-2', 'other')],
        [utterance('u-3', 'seg-1'), utterance('u-4', null)],
      ],
      pageParams: [0, 50],
    }
    const otherCluster = { ...cluster, id: 'cluster-2', queueIds: ['q-2'], segmentIds: ['other-seg'] }
    client.setQueryData(queryKeys.queue.list({ limit: 20, offset: 0 }), [cluster, otherCluster])
    client.setQueryData(queryKeys.queue.list({ limit: 20, offset: 20 }), [cluster])
    client.setQueryData(queryKey, pages)
    resolveQueueCluster.mockResolvedValueOnce({ resolved_count: 1 })

    const { result } = renderHook(() => useResolveQueueClusterMutation(), { wrapper: wrapper(client) })
    await act(async () => { await result.current.mutateAsync({ cluster, contactId: 'contact-1' }) })

    await waitFor(() => expect(client.getQueryData(queryKey)).toEqual({
      pages: [
        [
          { ...utterance('u-1', 'seg-1'), speaker_contact_id: 'contact-1' },
          utterance('u-2', 'other'),
        ],
        [
          { ...utterance('u-3', 'seg-1'), speaker_contact_id: 'contact-1' },
          utterance('u-4', null),
        ],
      ],
      pageParams: [0, 50],
    }))
    expect(client.getQueryData(queryKeys.queue.list({ limit: 20, offset: 0 }))).toEqual([otherCluster])
    expect(client.getQueryData(queryKeys.queue.list({ limit: 20, offset: 20 }))).toEqual([])
    expect(invalidateQueries).toHaveBeenCalledTimes(resolveInvalidationRoots.length)
    for (const queryKey of resolveInvalidationRoots) {
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey })
    }
  })

  it('restores every affected queue and utterance page, rolls back live resolution, and preserves unrelated caches on failure', async () => {
    const client = createClient()
    const failingCluster = { ...cluster, segmentIds: ['seg-1', 'seg-2'] }
    const queuePageOne = [failingCluster, { ...cluster, id: 'cluster-2', queueIds: ['q-2'] }]
    const queuePageTwo = [failingCluster]
    const filteredQueuePage = [failingCluster]
    const utterancePageOne = [utterance('u-1', 'seg-1'), utterance('u-2', 'unrelated')]
    const utterancePageTwo = [utterance('u-3', 'seg-2'), utterance('u-4', null)]
    const sessionOneUtterances = { pages: [utterancePageOne, utterancePageTwo], pageParams: [0, 50] }
    const sessionTwoUtterances = {
      pages: [[utterance('u-5', 'seg-1')], [utterance('u-6', 'other')]],
      pageParams: [0, 50],
    }
    const unrelatedQueueCount = { count: 4 }
    const unrelatedSessions = [{ id: 'session-unrelated', title: 'Unrelated' }]
    const unrelatedSearch = { items: ['unrelated'] }
    const rollbackLive = vi.fn()
    const applyLiveResolution = vi.fn(() => rollbackLive)
    const api = deferred<{ resolved_count: number }>()
    const invalidateQueries = vi.spyOn(client, 'invalidateQueries')
    resolveQueueCluster.mockReturnValueOnce(api.promise)

    client.setQueryData(queryKeys.queue.list({ limit: 20, offset: 0 }), queuePageOne)
    client.setQueryData(queryKeys.queue.list({ limit: 20, offset: 20 }), queuePageTwo)
    client.setQueryData(queryKeys.queue.list({ limit: 20, offset: 0, q: 'follow' }), filteredQueuePage)
    client.setQueryData(queryKeys.queue.count(), unrelatedQueueCount)
    client.setQueryData(queryKeys.sessions.utterances('s-1'), sessionOneUtterances)
    client.setQueryData(queryKeys.sessions.utterances('s-2'), sessionTwoUtterances)
    client.setQueryData(queryKeys.sessions.list(), unrelatedSessions)
    client.setQueryData(queryKeys.search.results({ q: 'unrelated' }), unrelatedSearch)

    const { result } = renderHook(
      () => useResolveQueueClusterMutation({ onApplyLiveResolution: applyLiveResolution }),
      { wrapper: wrapper(client) },
    )
    const mutation = act(() => result.current.mutateAsync({ cluster: failingCluster, contactId: 'contact-1' }))

    await waitFor(() => {
      expect(client.getQueryData(queryKeys.queue.list({ limit: 20, offset: 0 }))).toEqual([
        queuePageOne[1],
      ])
    })
    expect(client.getQueryData(queryKeys.queue.list({ limit: 20, offset: 20 }))).toEqual([])
    expect(client.getQueryData(queryKeys.queue.list({ limit: 20, offset: 0, q: 'follow' }))).toEqual([])
    expect(client.getQueryData(queryKeys.sessions.utterances('s-1'))).toEqual({
      pages: [
        [
          { ...utterance('u-1', 'seg-1'), speaker_contact_id: 'contact-1' },
          utterance('u-2', 'unrelated'),
        ],
        [
          { ...utterance('u-3', 'seg-2'), speaker_contact_id: 'contact-1' },
          utterance('u-4', null),
        ],
      ],
      pageParams: [0, 50],
    })
    expect(client.getQueryData(queryKeys.sessions.utterances('s-2'))).toEqual({
      pages: [[{ ...utterance('u-5', 'seg-1'), speaker_contact_id: 'contact-1' }], [utterance('u-6', 'other')]],
      pageParams: [0, 50],
    })
    expect(client.getQueryData(queryKeys.queue.count())).toEqual(unrelatedQueueCount)
    expect(client.getQueryData(queryKeys.sessions.list())).toEqual(unrelatedSessions)
    expect(client.getQueryData(queryKeys.search.results({ q: 'unrelated' }))).toEqual(unrelatedSearch)

    api.reject(new Error('resolve failed'))
    await expect(mutation).rejects.toThrow('resolve failed')

    expect(client.getQueryData(queryKeys.queue.list({ limit: 20, offset: 0 }))).toEqual(queuePageOne)
    expect(client.getQueryData(queryKeys.queue.list({ limit: 20, offset: 20 }))).toEqual(queuePageTwo)
    expect(client.getQueryData(queryKeys.queue.list({ limit: 20, offset: 0, q: 'follow' }))).toEqual(filteredQueuePage)
    expect(client.getQueryData(queryKeys.sessions.utterances('s-1'))).toEqual(sessionOneUtterances)
    expect(client.getQueryData(queryKeys.sessions.utterances('s-2'))).toEqual(sessionTwoUtterances)
    expect(client.getQueryData(queryKeys.queue.count())).toEqual(unrelatedQueueCount)
    expect(client.getQueryData(queryKeys.sessions.list())).toEqual(unrelatedSessions)
    expect(client.getQueryData(queryKeys.search.results({ q: 'unrelated' }))).toEqual(unrelatedSearch)
    expect(applyLiveResolution).toHaveBeenCalledWith(['seg-1', 'seg-2'], 'contact-1')
    expect(rollbackLive).toHaveBeenCalledOnce()

    expect(invalidateQueries).toHaveBeenCalledTimes(resolveInvalidationRoots.length)
    for (const queryKey of resolveInvalidationRoots) {
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey })
    }
  })

  it('handles empty queue and segment IDs without patching utterances with missing segment IDs', async () => {
    const client = createClient()
    const emptyCluster = { ...cluster, id: 'empty-cluster', queueIds: [], segmentIds: [] }
    const queryKey = queryKeys.sessions.utterances('s-1')
    const pages = { pages: [[utterance('', null), utterance('u-2', 'other')]], pageParams: [0] }
    const applyLiveResolution = vi.fn()
    client.setQueryData(queryKeys.queue.list({ limit: 20, offset: 0 }), [emptyCluster])
    client.setQueryData(queryKey, pages)
    resolveQueueCluster.mockResolvedValueOnce({ resolved_count: 0 })

    const { result } = renderHook(
      () => useResolveQueueClusterMutation({ onApplyLiveResolution: applyLiveResolution }),
      { wrapper: wrapper(client) },
    )
    await act(async () => { await result.current.mutateAsync({ cluster: emptyCluster, contactId: 'contact-1' }) })

    expect(resolveQueueCluster).toHaveBeenCalledWith([], 'contact-1')
    expect(applyLiveResolution).toHaveBeenCalledWith([], 'contact-1')
    expect(client.getQueryData(queryKey)).toEqual(pages)
    expect(client.getQueryData(queryKeys.queue.list({ limit: 20, offset: 0 }))).toEqual([])
  })
})
