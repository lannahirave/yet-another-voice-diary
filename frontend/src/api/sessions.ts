import type { ApiSession, ApiUtterance } from '../types/api'
import { apiFetch } from './client'

export const listSessions = () => apiFetch<ApiSession[]>('/sessions')

export const getSession = (id: string) => apiFetch<ApiSession>(`/sessions/${id}`)

export const createSession = (title: string, languageHint?: string) =>
  apiFetch<ApiSession>('/sessions', {
    method: 'POST',
    body: JSON.stringify({ title, language_hint: languageHint ?? null, notes: '' }),
  })

export const updateSession = (id: string, patch: { title?: string; notes?: string }) =>
  apiFetch<ApiSession>(`/sessions/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })

export const deleteSession = (id: string) =>
  apiFetch<void>(`/sessions/${id}`, { method: 'DELETE' })

export const listUtterances = (sessionId: string) =>
  apiFetch<ApiUtterance[]>(`/sessions/${sessionId}/utterances`)
