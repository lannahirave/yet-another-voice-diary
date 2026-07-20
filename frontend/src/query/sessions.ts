import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { adaptSession, adaptUtterance } from '../api/adapters'
import {
  deleteUtterance,
  identifyUtterance,
  listSessions,
  listUtterances,
} from '../api/sessions'
import type { ApiUtterance } from '../types/api'
import { queryKeys } from './keys'

export const SESSION_UTTERANCE_PAGE_SIZE = 50

type SessionUtteranceCache =
  | ApiUtterance[]
  | { pages: ApiUtterance[][]; pageParams: number[] }

export function useSessionsListQuery() {
  return useQuery({
    queryKey: queryKeys.sessions.list(),
    queryFn: listSessions,
    select: (sessions) => sessions.map(adaptSession),
    refetchOnMount: true,
  })
}

export function useSessionUtterancesQuery(sessionId: string | null) {
  return useInfiniteQuery({
    queryKey: sessionId
      ? queryKeys.sessions.utterances(sessionId)
      : [...queryKeys.sessions.utterancesRoot(), 'disabled'] as const,
    queryFn: ({ pageParam }) =>
      listUtterances(sessionId as string, pageParam, SESSION_UTTERANCE_PAGE_SIZE),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) =>
      lastPage.length < SESSION_UTTERANCE_PAGE_SIZE
        ? undefined
        : allPages.length * SESSION_UTTERANCE_PAGE_SIZE,
    enabled: !!sessionId,
    select: (pages) => pages.pages.flat().map(adaptUtterance),
  })
}

export function useIdentifyUtteranceMutation(sessionId: string | null) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({
      utteranceId,
      contactId,
    }: {
      utteranceId: string
      contactId: string
    }) => identifyUtterance(utteranceId, contactId),
    onSuccess: async () => {
      if (sessionId) {
        await queryClient.invalidateQueries({
          queryKey: queryKeys.sessions.utterances(sessionId),
        })
      }
      await queryClient.invalidateQueries({
        queryKey: queryKeys.contacts.list(),
      })
    },
  })
}

export function useDeleteUtteranceMutation(sessionId: string | null) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (utteranceId: string) => deleteUtterance(utteranceId),
    onMutate: async (utteranceId) => {
      if (!sessionId) return null

      const queryKey = queryKeys.sessions.utterances(sessionId)
      await queryClient.cancelQueries({ queryKey })
      const previous = queryClient.getQueryData<SessionUtteranceCache>(queryKey)

      queryClient.setQueryData<SessionUtteranceCache | undefined>(
        queryKey,
        (data) => {
          if (!data) return data
          if (Array.isArray(data)) {
            return data.filter((utterance) => utterance.id !== utteranceId)
          }
          return {
            ...data,
            pages: data.pages.map((page) =>
              page.filter((utterance) => utterance.id !== utteranceId),
            ),
          }
        },
      )

      return { queryKey, previous }
    },
    onError: (_error, _utteranceId, context) => {
      if (!context) return
      queryClient.setQueryData(context.queryKey, context.previous)
    },
    onSettled: async () => {
      if (sessionId) {
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: queryKeys.sessions.utterances(sessionId),
          }),
          queryClient.invalidateQueries({
            queryKey: queryKeys.sessions.list(),
          }),
        ])
      }
    },
  })
}
