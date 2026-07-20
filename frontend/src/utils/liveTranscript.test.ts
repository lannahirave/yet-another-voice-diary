import { describe, expect, it } from 'vitest'
import type { Utterance } from '../types/domain'
import {
  appendLiveUtterance,
  deriveLiveTranscriptStats,
  removeLiveUtterance,
  restoreLiveUtterance,
  updateSpeakerBySegment,
  updateSpeakerBySegments,
} from './liveTranscript'

function makeUtterance(overrides: Partial<Utterance> = {}): Utterance {
  return {
    id: 'utt-1',
    speakerId: null,
    speakerSegmentId: 'seg-1',
    time: '0:01',
    text: 'first',
    startedMs: 1000,
    endedMs: 2000,
    ...overrides,
  }
}

describe('live transcript', () => {
  it('keeps one visible row per persisted utterance in chronological order', () => {
    const first = makeUtterance()
    const second = makeUtterance({ id: 'utt-2', startedMs: 3000, endedMs: 4000, text: 'second' })
    const earlier = makeUtterance({ id: 'utt-3', startedMs: 500, endedMs: 900, text: 'earlier' })

    expect(appendLiveUtterance(appendLiveUtterance([first], second), earlier))
      .toEqual([earlier, first, second])
  })

  it('updates an existing persisted row instead of duplicating it', () => {
    const original = makeUtterance()
    const updated = makeUtterance({ text: 'updated' })

    expect(appendLiveUtterance([original], updated)).toEqual([updated])
  })

  it('removes and restores a row without replacing newer arrivals', () => {
    const first = makeUtterance()
    const second = makeUtterance({ id: 'utt-2', text: 'second', startedMs: 3000, endedMs: 4000 })
    const third = makeUtterance({ id: 'utt-3', text: 'third', startedMs: 5000, endedMs: 6000 })
    const removed = removeLiveUtterance([first, second, third], 'utt-2')

    expect(removed.utterances).toEqual([first, third])
    expect(removed.removed?.index).toBe(1)
    expect(restoreLiveUtterance(
      appendLiveUtterance(removed.utterances, makeUtterance({ id: 'utt-4', startedMs: 7000 })),
      removed.removed!,
    )).toEqual([first, second, third, expect.objectContaining({ id: 'utt-4' })])
  })

  it('patches speakers by one or many segment IDs', () => {
    const first = makeUtterance()
    const second = makeUtterance({ id: 'utt-2', speakerSegmentId: 'seg-2' })

    const one = updateSpeakerBySegment([first, second], 'seg-1', 'contact-1')
    expect(one.map((utterance) => utterance.speakerId)).toEqual(['contact-1', null])
    expect(updateSpeakerBySegments(one, ['seg-1', 'seg-2'], 'contact-2')
      .map((utterance) => utterance.speakerId)).toEqual(['contact-2', 'contact-2'])
  })

  it('derives duration-based speaker and unknown statistics', () => {
    const stats = deriveLiveTranscriptStats([
      makeUtterance({ speakerId: 'contact-1', startedMs: 0, endedMs: 2000 }),
      makeUtterance({ id: 'utt-2', startedMs: 3000, endedMs: 5000 }),
    ])

    expect(stats.speakerStats['contact-1'].ms).toBe(2000)
    expect(stats.speakerStats.__unk__.ms).toBe(2000)
    expect(stats.unknownInSession).toBe(1)
    expect(stats.totalMs).toBe(4000)
  })
})
