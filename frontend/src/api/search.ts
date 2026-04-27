import type { ApiSearchResponse } from '../types/api'
import { apiFetch } from './client'

export interface SearchFilters {
  sessionId?: string
  language?: string
  limit?: number
}

export const searchUtterances = (q: string, filters: SearchFilters = {}) => {
  const params = new URLSearchParams({ q })
  if (filters.sessionId) params.set('session_id', filters.sessionId)
  if (filters.language) params.set('language', filters.language)
  if (filters.limit != null) params.set('limit', String(filters.limit))
  return apiFetch<ApiSearchResponse>(`/search?${params.toString()}`)
}
