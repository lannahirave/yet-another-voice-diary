import type { ApiContact, ApiUtterance } from '../types/api'
import { apiFetch } from './client'

export const listContacts = () => apiFetch<ApiContact[]>('/contacts')

export const listContactUtterances = (id: string) =>
  apiFetch<ApiUtterance[]>(`/contacts/${id}/utterances`)

export const getContact = (id: string) => apiFetch<ApiContact>(`/contacts/${id}`)

export const createContact = (name: string, notes = '') =>
  apiFetch<ApiContact>('/contacts', {
    method: 'POST',
    body: JSON.stringify({ name, notes }),
  })

export const updateContact = (id: string, patch: { name?: string; notes?: string }) =>
  apiFetch<ApiContact>(`/contacts/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })

export const deleteContact = (id: string) =>
  apiFetch<void>(`/contacts/${id}`, { method: 'DELETE' })

export const mergeContacts = (targetId: string, sourceId: string) =>
  apiFetch<ApiContact>(`/contacts/${targetId}/merge`, {
    method: 'POST',
    body: JSON.stringify({ source_id: sourceId }),
  })
