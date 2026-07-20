import type { Utterance } from '../types/domain'

export interface RemovedUtterance {
  utterance: Utterance
  index: number
}

export interface SpeakerStat {
  speakerId: string | null
  ms: number
  order: number
}

export interface LiveTranscriptStats {
  speakerStats: Record<string, SpeakerStat>
  totalMs: number
  unknownInSession: number
}

/** Append one persisted utterance while preserving chronological order. */
export function appendLiveUtterance(
  utterances: Utterance[],
  utterance: Utterance,
): Utterance[] {
  const existingIndex = utterances.findIndex((item) => item.id === utterance.id)
  const next = existingIndex >= 0
    ? utterances.map((item, index) => index === existingIndex ? utterance : item)
    : [...utterances, utterance]

  return next
    .map((item, index) => ({ item, index }))
    .sort((a, b) => {
      if (a.item.startedMs === undefined || b.item.startedMs === undefined) {
        return a.index - b.index
      }
      return a.item.startedMs - b.item.startedMs || a.index - b.index
    })
    .map(({ item }) => item)
}

export function updateSpeakerBySegment(
  utterances: Utterance[],
  segmentId: string,
  contactId: string,
): Utterance[] {
  let changed = false
  const next = utterances.map((utterance) => {
    if (utterance.speakerSegmentId !== segmentId) return utterance
    changed = true
    return { ...utterance, speakerId: contactId }
  })
  return changed ? next : utterances
}

export function updateSpeakerBySegments(
  utterances: Utterance[],
  segmentIds: string[],
  contactId: string,
): Utterance[] {
  const idSet = new Set(segmentIds)
  let changed = false
  const next = utterances.map((utterance) => {
    if (!utterance.speakerSegmentId || !idSet.has(utterance.speakerSegmentId)) {
      return utterance
    }
    changed = true
    return { ...utterance, speakerId: contactId }
  })
  return changed ? next : utterances
}

export function removeLiveUtterance(
  utterances: Utterance[],
  utteranceId: string,
): { utterances: Utterance[]; removed: RemovedUtterance | null } {
  const index = utterances.findIndex((utterance) => utterance.id === utteranceId)
  if (index < 0) return { utterances, removed: null }

  return {
    utterances: [...utterances.slice(0, index), ...utterances.slice(index + 1)],
    removed: { utterance: utterances[index], index },
  }
}

/** Restore only the failed deletion; preserve utterances received meanwhile. */
export function restoreLiveUtterance(
  utterances: Utterance[],
  removed: RemovedUtterance,
): Utterance[] {
  if (utterances.some((utterance) => utterance.id === removed.utterance.id)) {
    return utterances
  }

  const index = Math.min(removed.index, utterances.length)
  return [
    ...utterances.slice(0, index),
    removed.utterance,
    ...utterances.slice(index),
  ]
}

function utteranceDurationMs(utterance: Utterance): number {
  const duration = (utterance.endedMs ?? 0) - (utterance.startedMs ?? 0)
  return duration > 0 ? duration : 4500
}

export function deriveLiveTranscriptStats(
  utterances: Utterance[],
): LiveTranscriptStats {
  const speakerStats = utterances.reduce<Record<string, SpeakerStat>>((acc, utterance, index) => {
    const key = utterance.speakerId ?? '__unk__'
    if (!acc[key]) {
      acc[key] = { speakerId: utterance.speakerId, ms: 0, order: index }
    }
    acc[key].ms += utteranceDurationMs(utterance)
    return acc
  }, {})

  const totalMs = Object.values(speakerStats).reduce((sum, stat) => sum + stat.ms, 0) || 1
  const unknownInSession = utterances.filter(
    (utterance) => !utterance.speakerId && utterance.speakerSegmentId != null,
  ).length

  return { speakerStats, totalMs, unknownInSession }
}
