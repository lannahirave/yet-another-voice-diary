import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { adaptQueueCluster } from '../api/adapters'
import { resolveQueueCluster, skipQueueCluster, deleteQueueCluster, listQueue, getQueueCount, getQueueSessions } from '../api/queue'
import type { UnknownQueueItem, Utterance } from '../types/domain'
import { queryKeys } from './keys'

interface ResolveQueueVariables {
  cluster: UnknownQueueItem
  contactId: string
}

interface SkipQueueVariables {
  cluster: UnknownQueueItem
}

interface ResolveQueueOptions {
  onApplyLiveResolution?: (segmentIds: string[], contactId: string) => (() => void) | void
}

function patchSessionUtterances(
  utterances: Utterance[] | undefined,
  segmentIds: string[],
  contactId: string,
): Utterance[] | undefined {
  if (!utterances) return utterances

  const idSet = new Set(segmentIds)
  let changed = false
  const next = utterances.map((utterance) => {
    if (!utterance.speakerSegmentId || !idSet.has(utterance.speakerSegmentId)) {
      return utterance
    }
    changed = true
    return { ...utterance, speakerId: contactId }
  })

  return changed ? next : utterances
}

export function useQueueListQuery(
  limit = 20,
  offset = 0,
  q?: string | null,
  sessionId?: string | null,
) {
  return useQuery({
    queryKey: queryKeys.queue.list({ limit, offset, q: q ?? undefined, sessionId: sessionId ?? undefined }),
    queryFn: () => listQueue(limit, offset, q, sessionId),
    staleTime: 5_000,
    placeholderData: (prev) => prev,
    select: (clusters) => clusters.map((cluster) => adaptQueueCluster(cluster)),
  })
}

export function useQueueCountQuery() {
  return useQuery({
    queryKey: queryKeys.queue.count(),
    queryFn: getQueueCount,
    staleTime: 10_000,
    select: (data) => data.count,
  })
}

export function useQueueSessionsQuery() {
  return useQuery({
    queryKey: queryKeys.queue.sessions(),
    queryFn: getQueueSessions,
    staleTime: 15_000,
  })
}

export function useResolveQueueClusterMutation(options: ResolveQueueOptions = {}) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ cluster, contactId }: ResolveQueueVariables) =>
      resolveQueueCluster(cluster.queueIds, contactId),
    onMutate: async ({ cluster, contactId }) => {
      await Promise.all([
        queryClient.cancelQueries({ queryKey: queryKeys.queue.listRoot() }),
        queryClient.cancelQueries({ queryKey: queryKeys.sessions.utterancesRoot() }),
      ])

      const previousQueue = queryClient.getQueriesData<UnknownQueueItem[]>({
        queryKey: queryKeys.queue.listRoot(),
      })
      const previousSessionUtterances = queryClient.getQueriesData<Utterance[]>({
        queryKey: queryKeys.sessions.utterancesRoot(),
      })
      const rollbackLive = options.onApplyLiveResolution?.(cluster.segmentIds, contactId)

      queryClient.setQueriesData<UnknownQueueItem[]>(
        { queryKey: queryKeys.queue.listRoot() },
        (existing) => existing?.filter((item) => item.id !== cluster.id) ?? [],
      )

      queryClient.setQueriesData<Utterance[]>(
        { queryKey: queryKeys.sessions.utterancesRoot() },
        (existing) => patchSessionUtterances(existing, cluster.segmentIds, contactId),
      )

      return { previousQueue, previousSessionUtterances, rollbackLive }
    },
    onError: (_error, _variables, context) => {
      if (!context) return

      for (const [key, data] of context.previousQueue) {
        queryClient.setQueryData(key, data)
      }
      for (const [key, data] of context.previousSessionUtterances) {
        queryClient.setQueryData(key, data)
      }
      context.rollbackLive?.()
    },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.queue.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.contacts.list() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.contacts.utterancesRoot() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.sessions.list() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.sessions.utterancesRoot() }),
      ])
    },
  })
}

export function useSkipQueueClusterMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ cluster }: SkipQueueVariables) => skipQueueCluster(cluster.queueIds),
    onMutate: async ({ cluster }) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.queue.listRoot() })

      const previousQueue = queryClient.getQueriesData<UnknownQueueItem[]>({
        queryKey: queryKeys.queue.listRoot(),
      })
      queryClient.setQueriesData<UnknownQueueItem[]>(
        { queryKey: queryKeys.queue.listRoot() },
        (existing) => existing?.filter((item) => item.id !== cluster.id) ?? [],
      )

      return { previousQueue }
    },
    onError: (_error, _variables, context) => {
      for (const [key, data] of context?.previousQueue ?? []) {
        queryClient.setQueryData(key, data)
      }
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.queue.all })
    },
  })
}

export function useDeleteQueueClusterMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ cluster }: SkipQueueVariables) => deleteQueueCluster(cluster.queueIds),
    onMutate: async ({ cluster }) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.queue.listRoot() })

      const previousQueue = queryClient.getQueriesData<UnknownQueueItem[]>({
        queryKey: queryKeys.queue.listRoot(),
      })
      queryClient.setQueriesData<UnknownQueueItem[]>(
        { queryKey: queryKeys.queue.listRoot() },
        (existing) => existing?.filter((item) => item.id !== cluster.id) ?? [],
      )

      return { previousQueue }
    },
    onError: (_error, _variables, context) => {
      for (const [key, data] of context?.previousQueue ?? []) {
        queryClient.setQueryData(key, data)
      }
    },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.queue.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.sessions.list() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.sessions.utterancesRoot() }),
      ])
    },
  })
}
