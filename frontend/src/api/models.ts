import type {
  ApiModelProgressEvent,
  ApiModelStatusMap,
  ApiProviderStatus,
} from '../types/api'
import { BASE_URL, apiFetch } from './client'

export const getModelStatus = () => apiFetch<ApiModelStatusMap>('/models/status')

export const loadModel = (type: string) =>
  apiFetch<ApiProviderStatus>(`/models/${type}/load`, { method: 'POST' })

export const unloadModel = (type: string) =>
  apiFetch<ApiProviderStatus>(`/models/${type}/unload`, { method: 'POST' })

/**
 * Subscribe to backend model load progress via SSE. Returns a disposer.
 * Calls ``onEvent`` for each ``data:`` event received until the stream ends or
 * the disposer is called.
 */
export function subscribeModelProgress(
  type: string,
  onEvent: (event: ApiModelProgressEvent) => void,
  onError?: (err: Event) => void,
): () => void {
  const source = new EventSource(`${BASE_URL}/models/${type}/download-progress`)
  source.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data) as ApiModelProgressEvent)
    } catch {
      // ignore malformed event
    }
  }
  source.onerror = (err) => {
    if (onError) onError(err)
    source.close()
  }
  return () => source.close()
}
