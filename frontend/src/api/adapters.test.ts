import { describe, expect, it } from 'vitest'
import {
  adaptContact,
  adaptSession,
  adaptUtterance,
  adaptQueueCluster,
} from './adapters'
import type { ApiContact, ApiSession, ApiUtterance, ApiQueueCluster } from '../types/api'

describe('adaptContact', () => {
  it('maps all fields and generates initials', () => {
    const api: ApiContact = {
      id: 'c1',
      name: 'John Doe',
      notes: '',
      created_at: '2026-04-15T10:00:00Z',
      profile_count: 3,
      session_count: 5,
      confidence: 0.85,
    }

    const contact = adaptContact(api)

    expect(contact.id).toBe('c1')
    expect(contact.name).toBe('John Doe')
    expect(contact.initials).toBe('JD')
    expect(contact.color).toBeTruthy()
    expect(contact.sessions).toBe(5)
    expect(contact.profileCount).toBe(3)
    expect(contact.confidence).toBe(0.85)
    expect(contact.pitch).toBe('середній')
    expect(contact.tempo).toBe('середній')
  })

  it('handles single-word name', () => {
    const api: ApiContact = {
      id: 'c2',
      name: 'Alice',
      notes: '',
      created_at: '2026-01-01T00:00:00Z',
      profile_count: 1,
      session_count: 2,
      confidence: 0.5,
    }

    const contact = adaptContact(api)
    expect(contact.initials).toBe('A')
  })

  it('handles empty name', () => {
    const api: ApiContact = {
      id: 'c3',
      name: '',
      notes: '',
      created_at: '2026-01-01T00:00:00Z',
      profile_count: 0,
      session_count: 0,
      confidence: 0,
    }

    const contact = adaptContact(api)
    expect(contact.initials).toBe('')
  })

  it('handles name with extra whitespace', () => {
    const api: ApiContact = {
      id: 'c4',
      name: 'Jane   Doe',
      notes: '',
      created_at: '2026-01-01T00:00:00Z',
      profile_count: 1,
      session_count: 1,
      confidence: 0,
    }

    const contact = adaptContact(api)
    expect(contact.initials).toBe('JD')
  })

  it('returns same color for same id', () => {
    const api1: ApiContact = {
      id: 'c5', name: 'A', notes: '', created_at: '2026-01-01T00:00:00Z',
      profile_count: 1, session_count: 1, confidence: 0,
    }
    const api2: ApiContact = {
      id: 'c5', name: 'B', notes: '', created_at: '2026-01-01T00:00:00Z',
      profile_count: 1, session_count: 1, confidence: 0,
    }

    expect(adaptContact(api1).color).toBe(adaptContact(api2).color)
  })

  it('handles null confidence', () => {
    const api: ApiContact = {
      id: 'c6', name: 'Test', notes: '', created_at: '2026-01-01T00:00:00Z',
      profile_count: 0, session_count: 0, confidence: null as unknown as number,
    }

    const contact = adaptContact(api)
    expect(contact.confidence).toBe(0)
  })
})

describe('adaptSession', () => {
  it('maps session fields with formatted date/time', () => {
    const api: ApiSession = {
      id: 's1',
      title: 'Team sync',
      started_at: '2026-05-01T09:30:00Z',
      ended_at: '2026-05-01T10:15:00Z',
      notes: '',
      language_hint: null,
      utterance_count: 12,
      speakers: ['c1', 'c2'],
    }

    const session = adaptSession(api)

    expect(session.id).toBe('s1')
    expect(session.title).toBe('Team sync')
    expect(session.date).toBeTruthy()
    expect(session.time).toBeTruthy()
    expect(session.duration).toBeTruthy()
    expect(session.utteranceCount).toBe(12)
    expect(session.speakers).toEqual(['c1', 'c2'])
  })

  it('defaults empty title to placeholder', () => {
    const api: ApiSession = {
      id: 's2',
      title: '',
      started_at: '2026-01-01T00:00:00Z',
      ended_at: null,
      notes: '',
      language_hint: null,
      utterance_count: 0,
      speakers: [],
    }

    const session = adaptSession(api)
    expect(session.title).toBe('Без назви')
  })

  it('handles null ended_at — duration is empty', () => {
    const api: ApiSession = {
      id: 's3',
      title: 'Ongoing',
      started_at: '2026-05-01T09:00:00Z',
      ended_at: null,
      notes: '',
      language_hint: null,
      utterance_count: 2,
      speakers: [],
    }

    const session = adaptSession(api)
    expect(session.duration).toBe('')
  })

  it('maps language hint to languages array', () => {
    const apiUK: ApiSession = {
      id: 's4', title: 'Test', started_at: '2026-01-01T00:00:00Z',
      ended_at: null, notes: '', language_hint: 'UK', utterance_count: 1, speakers: [],
    }
    expect(adaptSession(apiUK).languages).toEqual(['UK'])

    const apiEN: ApiSession = {
      id: 's5', title: 'Test', started_at: '2026-01-01T00:00:00Z',
      ended_at: null, notes: '', language_hint: 'EN', utterance_count: 1, speakers: [],
    }
    expect(adaptSession(apiEN).languages).toEqual(['EN'])
  })
})

describe('adaptUtterance', () => {
  it('maps utterance fields correctly', () => {
    const api: ApiUtterance = {
      id: 'u1',
      session_id: 's1',
      started_ms: 5000,
      ended_ms: 12000,
      transcript: 'Hello world',
      language: 'EN',
      confidence: 0.95,
      speaker_segment_id: 'seg1',
      speaker_contact_id: 'c1',
      source: 'mic',
      session_started_at: '2026-05-01T09:30:00Z',
    }

    const utt = adaptUtterance(api)

    expect(utt.id).toBe('u1')
    expect(utt.speakerId).toBe('c1')
    expect(utt.speakerSegmentId).toBe('seg1')
    expect(utt.time).toBe('0:05')
    expect(utt.text).toBe('Hello world')
    expect(utt.lang).toBe('EN')
    expect(utt.source).toBe('mic')
    expect(utt.sessionStartedAt).toBe('2026-05-01T09:30:00Z')
  })

  it('handles system audio source', () => {
    const api: ApiUtterance = {
      id: 'u2', session_id: 's1', started_ms: 0, ended_ms: 1000,
      transcript: '', language: null, confidence: 0, speaker_segment_id: null,
      speaker_contact_id: null, source: 'system',
    }
    expect(adaptUtterance(api).source).toBe('system')
  })

  it('maps unknown language to undefined', () => {
    const api: ApiUtterance = {
      id: 'u3', session_id: 's1', started_ms: 0, ended_ms: 1000,
      transcript: '', language: 'DE', confidence: 0, speaker_segment_id: null,
      speaker_contact_id: null,
    }
    expect(adaptUtterance(api).lang).toBeUndefined()
  })
})

describe('adaptQueueCluster', () => {
  it('maps cluster fields including candidates', () => {
    const api: ApiQueueCluster = {
      id: 'q1',
      queue_ids: ['qq1', 'qq2'],
      segment_ids: ['seg1', 'seg2'],
      session_ids: ['sess-a'],
      session_titles: ['My Session'],
      duration_ms: 25000,
      fragment_count: 2,
      quote: 'Some transcript text',
      candidates: [
        { contact_id: 'c1', contact_name: 'Alice', score: 0.82 },
        { contact_id: 'c2', contact_name: 'Bob', score: 0.65 },
      ],
      created_at: '2026-05-01T09:30:00Z',
    }

    const item = adaptQueueCluster(api)

    expect(item.id).toBe('q1')
    expect(item.queueIds).toEqual(['qq1', 'qq2'])
    expect(item.segmentIds).toEqual(['seg1', 'seg2'])
    expect(item.sessionIds).toEqual(['sess-a'])
    expect(item.sessionTitles).toEqual(['My Session'])
    expect(item.sessionId).toBe('sess-a')
    expect(item.fragmentCount).toBe(2)
    expect(item.totalDuration).toBe('0:25')
    expect(item.quote).toBe('Some transcript text')
    expect(item.candidates).toEqual([
      { contactId: 'c1', score: 0.82 },
      { contactId: 'c2', score: 0.65 },
    ])
    expect(item.status).toBe('unresolved')
  })

  it('falls back to session_ids when session_titles is empty', () => {
    const api: ApiQueueCluster = {
      id: 'q2',
      queue_ids: ['qq1'],
      segment_ids: ['seg1'],
      session_ids: ['sess-x'],
      session_titles: [],
      duration_ms: 5000,
      fragment_count: 1,
      quote: '',
      candidates: [],
      created_at: '2026-05-01T00:00:00Z',
    }

    const item = adaptQueueCluster(api)
    expect(item.sessionTitles).toEqual(['sess-x'])
  })

  it('handles zero duration', () => {
    const api: ApiQueueCluster = {
      id: 'q3',
      queue_ids: ['qq1'],
      segment_ids: ['seg1'],
      session_ids: ['s1'],
      session_titles: ['S1'],
      duration_ms: 0,
      fragment_count: 1,
      quote: '',
      candidates: [],
      created_at: '2026-05-01T00:00:00Z',
    }

    const item = adaptQueueCluster(api)
    expect(item.totalDuration).toBe('')
  })
})
