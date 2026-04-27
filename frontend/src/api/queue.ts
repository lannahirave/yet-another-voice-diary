import type { ApiQueueCluster, ApiQueueResolveResponse } from '../types/api'
import { apiFetch } from './client'

export const listQueue = () => apiFetch<ApiQueueCluster[]>('/unknown-queue')

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
