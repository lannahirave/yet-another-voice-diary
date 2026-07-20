/** Map API shapes to frontend domain types */
import type { Contact, Session, Utterance, UnknownQueueItem } from '../types/domain'
import type { ApiContact, ApiSession, ApiUtterance, ApiQueueCluster } from '../types/api'

const PALETTE = [
  '#7C6FFF', '#3DD68C', '#F59E0B', '#EC4899',
  '#06B6D4', '#84CC16', '#F97316', '#A78BFA',
]

const _colorCache = new Map<string, string>()

function hashColor(id: string): string {
  const cached = _colorCache.get(id)
  if (cached) return cached
  let h = 0
  for (let i = 0; i < id.length; i++) h = (Math.imul(31, h) + id.charCodeAt(i)) | 0
  const color = PALETTE[Math.abs(h) % PALETTE.length]
  _colorCache.set(id, color)
  return color
}

function toInitials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('')
}

export function adaptContact(api: ApiContact): Contact {
  return {
    id: api.id,
    name: api.name,
    initials: toInitials(api.name),
    color: hashColor(api.id),
    sessions: api.session_count,
    totalTime: 0,
    firstMet: new Date(api.created_at).toLocaleDateString('uk-UA', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    }),
    languages: [],
    profileCount: api.profile_count,
    confidence: api.confidence ?? 0,
    pitch: 'середній',
    tempo: 'середній',
    energy: 0,
    pitchHz: 0,
  }
}

function msToTime(ms: number): string {
  const s = Math.floor(ms / 1000)
  const m = Math.floor(s / 60)
  const ss = String(s % 60).padStart(2, '0')
  return `${m}:${ss}`
}

export function adaptUtterance(api: ApiUtterance): Utterance {
  return {
    id: api.id,
    speakerId: api.speaker_contact_id,
    speakerSegmentId: api.speaker_segment_id,
    time: msToTime(api.started_ms),
    text: api.transcript,
    lang: api.language === 'EN' ? 'EN' : api.language === 'UK' ? 'UK' : undefined,
    source: api.source === 'system' ? 'system' : 'mic',
    sessionStartedAt: api.session_started_at,
    startedMs: api.started_ms,
    endedMs: api.ended_ms,
  }
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('uk-UA', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('uk-UA', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatDuration(startIso: string, endIso: string | null): string {
  if (!endIso) return ''
  const diffS = Math.round(
    (new Date(endIso).getTime() - new Date(startIso).getTime()) / 1000,
  )
  const m = Math.floor(diffS / 60)
  const s = String(diffS % 60).padStart(2, '0')
  return `${m}:${s}`
}

export function adaptSession(api: ApiSession): Session {
  return {
    id: api.id,
    title: api.title || 'Без назви',
    date: formatDate(api.started_at),
    time: formatTime(api.started_at),
    duration: formatDuration(api.started_at, api.ended_at),
    utteranceCount: api.utterance_count,
    languages: api.language_hint === 'EN' ? ['EN'] : api.language_hint === 'UK' ? ['UK'] : [],
    speakers: api.speakers,
    preview: '',
    recordingAvailable: api.recording_available ?? false,
    recordingSizeBytes: api.recording_size_bytes ?? 0,
    refinementStatus: api.refinement_status ?? null,
  }
}

function formatDurationMs(ms: number): string {
  if (ms <= 0) return ''
  const s = Math.round(ms / 1000)
  if (s < 60) return `0:${String(s).padStart(2, '0')}`
  const m = Math.floor(s / 60)
  return `${m}:${String(s % 60).padStart(2, '0')}`
}

function queueDisplayLabel(id: string): string {
  const normalized = id.replace(/[^a-zA-Z0-9]+/g, '').toUpperCase()
  return normalized.slice(0, 6) || '000000'
}

export function adaptQueueCluster(api: ApiQueueCluster): UnknownQueueItem {
  const sessionTitles = api.session_titles?.length
    ? api.session_titles
    : api.session_ids
  return {
    id: api.id,
    queueIds: api.queue_ids,
    segmentIds: api.segment_ids,
    sessionIds: api.session_ids,
    sessionTitles,
    sessionId: api.session_ids[0] ?? '',
    sessionTitle: sessionTitles[0] ?? api.session_ids[0] ?? '',
    sessionDate: new Date(api.created_at).toLocaleDateString('uk-UA', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    }),
    label: queueDisplayLabel(api.id),
    fragmentCount: api.fragment_count || api.queue_ids.length,
    totalDuration: formatDurationMs(api.duration_ms),
    quote: api.quote ?? '',
    candidates: api.candidates.map((c) => ({ contactId: c.contact_id, score: c.score })),
    status: 'unresolved',
  }
}
