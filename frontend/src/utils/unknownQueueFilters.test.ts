import { describe, expect, it } from 'vitest'
import type { UnknownQueueItem } from '../types/domain'
import {
  deriveQueueSessionOptions,
  filterUnknownQueueItems,
  normalizeQueueSessionFilter,
} from './unknownQueueFilters'

const ITEMS: UnknownQueueItem[] = [
  {
    id: 'queue-1',
    queueIds: ['queue-1'],
    segmentIds: ['seg-1'],
    sessionIds: ['session-a'],
    sessionTitles: ['Alpha planning'],
    sessionId: 'session-a',
    sessionTitle: 'Alpha planning',
    sessionDate: '26 Apr 2026',
    label: '000001',
    fragmentCount: 2,
    totalDuration: '0:25',
    quote: 'Need to review the architecture document',
    candidates: [{ contactId: 'alice', score: 0.82 }],
    status: 'unresolved',
  },
  {
    id: 'queue-2',
    queueIds: ['queue-2'],
    segmentIds: ['seg-2'],
    sessionIds: ['session-b'],
    sessionTitles: ['Beta interview'],
    sessionId: 'session-b',
    sessionTitle: 'Beta interview',
    sessionDate: '26 Apr 2026',
    label: '000002',
    fragmentCount: 1,
    totalDuration: '0:12',
    quote: 'Candidate prefers async communication',
    candidates: [{ contactId: 'bob', score: 0.77 }],
    status: 'unresolved',
  },
  {
    id: 'queue-3',
    queueIds: ['queue-3'],
    segmentIds: ['seg-3'],
    sessionIds: ['session-a', 'session-c'],
    sessionTitles: ['Alpha planning', 'Gamma sync'],
    sessionId: 'session-a',
    sessionTitle: 'Alpha planning',
    sessionDate: '26 Apr 2026',
    label: '000003',
    fragmentCount: 4,
    totalDuration: '1:05',
    quote: 'Gamma release has a blocker',
    candidates: [{ contactId: 'carol', score: 0.81 }],
    status: 'unresolved',
  },
]

describe('deriveQueueSessionOptions', () => {
  it('collects unique session ids with their titles', () => {
    expect(deriveQueueSessionOptions(ITEMS)).toEqual([
      { sessionId: 'session-a', sessionTitle: 'Alpha planning' },
      { sessionId: 'session-b', sessionTitle: 'Beta interview' },
      { sessionId: 'session-c', sessionTitle: 'Gamma sync' },
    ])
  })
})

describe('normalizeQueueSessionFilter', () => {
  const sessionOptions = deriveQueueSessionOptions(ITEMS)

  it('resets current filter to all when there is no active current session', () => {
    expect(normalizeQueueSessionFilter('current', null, sessionOptions)).toBe('all')
  })

  it('resets stale concrete session filters to all', () => {
    expect(normalizeQueueSessionFilter('missing-session', 'session-a', sessionOptions)).toBe('all')
  })
})

describe('filterUnknownQueueItems', () => {
  it('filters by a concrete session id', () => {
    const filtered = filterUnknownQueueItems({
      items: ITEMS,
      searchQuery: '',
      sessionFilter: 'session-b',
    })
    expect(filtered.map((item) => item.id)).toEqual(['queue-2'])
  })

  it('filters by the current session shortcut', () => {
    const filtered = filterUnknownQueueItems({
      items: ITEMS,
      searchQuery: '',
      sessionFilter: 'current',
      currentSessionId: 'session-a',
    })
    expect(filtered.map((item) => item.id)).toEqual(['queue-1', 'queue-3'])
  })

  it('searches through session titles, quote text, and candidate names', () => {
    expect(
      filterUnknownQueueItems({
        items: ITEMS,
        searchQuery: 'gamma',
        sessionFilter: 'all',
      }).map((item) => item.id),
    ).toEqual(['queue-3'])

    expect(
      filterUnknownQueueItems({
        items: ITEMS,
        searchQuery: 'alice',
        sessionFilter: 'all',
        lookupContactName: (contactId) =>
          ({ alice: 'Alice Johnson', bob: 'Bob Smith', carol: 'Carol Young' }[contactId] ?? null),
      }).map((item) => item.id),
    ).toEqual(['queue-1'])
  })

  it('combines the text search with the session filter', () => {
    const filtered = filterUnknownQueueItems({
      items: ITEMS,
      searchQuery: 'planning',
      sessionFilter: 'session-b',
    })
    expect(filtered).toEqual([])
  })
})
