/** API response shapes — mirrors backend/api/schemas.py */

export interface ApiSession {
  id: string
  title: string
  started_at: string
  ended_at: string | null
  notes: string
  language_hint: string | null
  utterance_count: number
  speakers: string[]
}

export interface ApiUtterance {
  id: string
  session_id: string
  started_ms: number
  ended_ms: number
  transcript: string
  language: string | null
  confidence: number
  speaker_segment_id: string | null
  speaker_contact_id: string | null
  source?: string
}

export interface ApiContact {
  id: string
  name: string
  notes: string
  created_at: string
  profile_count: number
  session_count: number
  confidence: number
}

export interface ApiQueueCandidate {
  contact_id: string
  contact_name: string
  score: number
}

export interface ApiQueueItem {
  id: string
  speaker_segment_id: string
  session_id: string
  created_at: string
  resolved_contact_id: string | null
  resolved_at: string | null
  candidates: ApiQueueCandidate[]
}

export interface ApiQueueCluster {
  id: string
  queue_ids: string[]
  segment_ids: string[]
  session_ids: string[]
  session_titles: string[]
  created_at: string
  fragment_count: number
  duration_ms: number
  quote: string
  source?: string
  candidates: ApiQueueCandidate[]
}

export interface ApiQueueResolveResponse {
  resolved_count: number
  cascaded_count: number
}

export interface ApiSearchHit {
  utterance_id: string
  session_id: string
  session_title: string
  transcript: string
  language: string | null
  started_ms: number
  snippet: string
}

export interface ApiSearchResponse {
  query: string
  total: number
  hits: ApiSearchHit[]
}

export interface ApiProviderStatus {
  kind: string
  model_id: string
  state: string
  error: string | null
}

export interface ApiConfig {
  vad_threshold: number
  speaker_identification_threshold: number
  chunk_duration_ms: number
  unload_models_after_stop: boolean
  preload_on_start: boolean
  providers: ApiProviderStatus[]
}

export type ApiModelStatusMap = Record<string, ApiProviderStatus>

export interface ApiStorageInfo {
  db_path: string
  db_size_bytes: number
  exists: boolean
}

export interface ApiModelProgressEvent {
  kind: string
  model_id: string
  progress: number
  state: string
  message: string
}
