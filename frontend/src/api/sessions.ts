import type {
  ApiSession,
  ApiUtterance,
  ApiUtteranceCandidates,
  ApiUtteranceIdentifyResponse,
  ApiRefinementJob,
} from '../types/api'
import { apiFetch } from './client'

export const listSessions = () => apiFetch<ApiSession[]>('/sessions')

export const getSession = (id: string) => apiFetch<ApiSession>(`/sessions/${id}`)

export const createSession = (title?: string, languageHint?: string) =>
  apiFetch<ApiSession>('/sessions', {
    method: 'POST',
    body: JSON.stringify({ title: title ?? '', language_hint: languageHint }),
  })

export const updateSession = (
  id: string,
  payload: { title?: string; ended_at?: string; notes?: string },
) =>
  apiFetch<ApiSession>(`/sessions/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })

export const deleteSession = (id: string) =>
  apiFetch<void>(`/sessions/${id}`, { method: 'DELETE' })

export const listUtterances = (sessionId: string, offset = 0, limit = 50) =>
  apiFetch<ApiUtterance[]>(
    `/sessions/${sessionId}/utterances?offset=${offset}&limit=${limit}`,
  )

export const getUtteranceCandidates = (utteranceId: string) =>
  apiFetch<ApiUtteranceCandidates>(`/sessions/utterances/${utteranceId}/candidates`)

export const identifyUtterance = (utteranceId: string, contactId: string) =>
  apiFetch<ApiUtteranceIdentifyResponse>(`/sessions/utterances/${utteranceId}/identify`, {
    method: 'POST',
    body: JSON.stringify({ contact_id: contactId }),
  })

export const deleteUtterance = (utteranceId: string) =>
  apiFetch<void>(`/sessions/utterances/${utteranceId}`, { method: 'DELETE' })

export const getRefinement = (sessionId: string) =>
  apiFetch<ApiRefinementJob | null>(`/sessions/${sessionId}/refinement`)

export const startRefinement = (sessionId: string) =>
  apiFetch<ApiRefinementJob>(`/sessions/${sessionId}/refinement`, { method: 'POST' })

export const cancelRefinement = (sessionId: string) =>
  apiFetch<ApiRefinementJob | null>(`/sessions/${sessionId}/refinement/cancel`, { method: 'POST' })

export const deleteSessionRecording = (sessionId: string) =>
  apiFetch<void>(`/sessions/${sessionId}/recording`, { method: 'DELETE' })
