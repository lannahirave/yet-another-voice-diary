import { describe, expect, it } from 'vitest'
import { queryKeys } from './keys'

describe('queryKeys', () => {
  describe('contacts', () => {
    it('returns correct base key', () => {
      expect(queryKeys.contacts.all).toEqual(['contacts'])
    })

    it('returns correct list key', () => {
      expect(queryKeys.contacts.list()).toEqual(['contacts', 'list'])
    })

    it('returns correct utterances key for a contact', () => {
      expect(queryKeys.contacts.utterances('c1')).toEqual(['contacts', 'utterances', 'c1'])
    })
  })

  describe('queue', () => {
    it('returns correct base key', () => {
      expect(queryKeys.queue.all).toEqual(['queue'])
    })

    it('returns correct list key without params', () => {
      expect(queryKeys.queue.list()).toEqual(['queue', 'list', {}])
    })
    ;(expect(queryKeys.queue.list({})).toEqual(['queue', 'list', {}]))

    it('returns correct list key with params', () => {
      expect(queryKeys.queue.list({ limit: 10, offset: 0 })).toEqual([
        'queue', 'list', { limit: 10, offset: 0 },
      ])
    })

    it('returns correct list key with search and session filter', () => {
      expect(queryKeys.queue.list({ q: 'test', sessionId: 's1' })).toEqual([
        'queue', 'list', { q: 'test', sessionId: 's1' },
      ])
    })

    it('returns correct count key', () => {
      expect(queryKeys.queue.count()).toEqual(['queue', 'count'])
    })

    it('returns correct sessions key', () => {
      expect(queryKeys.queue.sessions()).toEqual(['queue', 'sessions'])
    })
  })

  describe('sessions', () => {
    it('returns correct base key', () => {
      expect(queryKeys.sessions.all).toEqual(['sessions'])
    })

    it('returns correct list key', () => {
      expect(queryKeys.sessions.list()).toEqual(['sessions', 'list'])
    })

    it('returns correct utterances key', () => {
      expect(queryKeys.sessions.utterances('sess-1')).toEqual([
        'sessions', 'utterances', 'sess-1',
      ])
    })
  })

  describe('search', () => {
    it('returns correct base key', () => {
      expect(queryKeys.search.all).toEqual(['search'])
    })

    it('returns correct results key with params', () => {
      expect(queryKeys.search.results({ q: 'hello', limit: 50 })).toEqual([
        'search', 'results', { q: 'hello', limit: 50 },
      ])
    })

    it('returns correct results key with language filter', () => {
      expect(queryKeys.search.results({ q: 'hello', language: 'UK', limit: 100 })).toEqual([
        'search', 'results', { q: 'hello', language: 'UK', limit: 100 },
      ])
    })
  })

  describe('config', () => {
    it('returns correct base key', () => {
      expect(queryKeys.config.all).toEqual(['config'])
    })

    it('returns correct current key', () => {
      expect(queryKeys.config.current()).toEqual(['config', 'current'])
    })

    it('returns correct storage key', () => {
      expect(queryKeys.config.storage()).toEqual(['config', 'storage'])
    })
  })
})
