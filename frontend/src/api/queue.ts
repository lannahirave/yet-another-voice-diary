import type { ApiQueueCluster, ApiQueueResolveResponse } from '../types/api'
import { apiFetch } from './client'

export const listQueue = (limit = 20, offset = 0) =>
  apiFetch<ApiQueueCluster[]>(`/unknown-queue?limit=${limit}&offset=${offset}`)

export const getQueueCount = () =>
  apiFetch<{ count: number }>('/unknown-queue/count')

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
