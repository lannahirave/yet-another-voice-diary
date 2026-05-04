export type Language = 'UK' | 'EN'

export type PitchLevel = 'низький' | 'середній' | 'високий'
export type TempoLevel = 'повільний' | 'середній' | 'швидкий'

export interface Contact {
  id: string
  name: string
  initials: string
  color: string
  sessions: number
  totalTime: number
  firstMet: string
  languages: Language[]
  profileCount: number
  confidence: number
  pitch: PitchLevel
  tempo: TempoLevel
  energy: number
  pitchHz: number
}

export interface Session {
  id: string
  title: string
  date: string
  time: string
  duration: string
  utteranceCount: number
  languages: Language[]
  speakers: string[]
  preview: string
}

export type AudioSource = 'mic' | 'system'

export interface Utterance {
  id: string
  speakerId: string | null
  speakerSegmentId?: string | null
  time: string
  text: string
  lang?: Language
  source?: AudioSource
  sessionStartedAt?: string
  /** Session-relative start in ms (for gap calculation). */
  startedMs?: number
  /** Session-relative end in ms. */
  endedMs?: number
}

export interface UnknownQueueCandidate {
  contactId: string
  score: number
}

export interface UnknownQueueItem {
  id: string
  queueIds: string[]
  segmentIds: string[]
  sessionIds: string[]
  sessionTitles: string[]
  sessionId: string
  sessionTitle: string
  sessionDate: string
  label: string
  fragmentCount: number
  totalDuration: string
  quote: string
  candidates: UnknownQueueCandidate[]
  status: 'unresolved' | 'resolved' | 'skipped'
}

export interface LiveUtterance {
  speakerId: string | null
  delay: number
  text: string
}

export type ScreenId =
  | 'session'
  | 'sessions'
  | 'queue'
  | 'contacts'
  | 'search'
  | 'settings'
