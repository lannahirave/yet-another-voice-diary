import type { ApiQueueCluster, ApiQueueResolveResponse } from '../types/api'
import { apiFetch } from './client'

export const listQueue = (
  limit = 20,
  offset = 0,
  q?: string | null,
  sessionId?: string | null,
) => {
  let path = `/unknown-queue?limit=${limit}&offset=${offset}`
  if (q) path += `&q=${encodeURIComponent(q)}`
  if (sessionId) path += `&session_id=${encodeURIComponent(sessionId)}`
  return apiFetch<ApiQueueCluster[]>(path)
}

export const getQueueCount = () =>
  apiFetch<{ count: number }>('/unknown-queue/count')

export const getQueueSessions = () =>
  apiFetch<Array<{ session_id: string; title: string; started_at: number }>>('/unknown-queue/sessions')

export const resolveQueueCluster = (queueIds: string[], contactId: string) =>
  apiFetch<ApiQueueResolveResponse>('/unknown-queue/resolve', {
    method: 'POST',
    body: JSON.stringify({ queue_ids: queueIds, contact_id: contactId }),
  })

export const skipQueueCluster = (queueIds: string[]) =>
  apiFetch<{ skipped_count: number }>('/unknown-queue/skip', {
    method: 'POST',
    body: JSON.stringify({ queue_ids: queueIds }),
  })
