import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { adaptSession, adaptUtterance } from '../api/adapters'
import {
  identifyUtterance,
  listSessions,
  listUtterances,
} from '../api/sessions'
import type { ApiUtterance } from '../types/api'
import type { Utterance } from '../types/domain'
import { queryKeys } from './keys'

export function useSessionsListQuery() {
  return useQuery({
    queryKey: queryKeys.sessions.list(),
    queryFn: listSessions,
    select: (sessions) => sessions.map(adaptSession),
  })
}

export function useSessionUtterancesQuery(sessionId: string | null) {
  return useQuery<ApiUtterance[], Error, Utterance[]>({
    queryKey: sessionId
      ? queryKeys.sessions.utterances(sessionId)
      : [...queryKeys.sessions.utterancesRoot(), 'disabled'] as const,
    queryFn: () => listUtterances(sessionId as string),
    enabled: !!sessionId,
    select: (utterances) => utterances.map(adaptUtterance),
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
