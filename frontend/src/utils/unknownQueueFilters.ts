import type { UnknownQueueItem } from '../types/domain'

export interface QueueSessionOption {
  sessionId: string
  sessionTitle: string
}

export interface FilterUnknownQueueItemsArgs {
  items: UnknownQueueItem[]
  searchQuery: string
  sessionFilter: string
  currentSessionId?: string | null
  lookupContactName?: (contactId: string) => string | null
}

export function deriveQueueSessionOptions(items: UnknownQueueItem[]): QueueSessionOption[] {
  const options = new Map<string, string>()
  for (const item of items) {
    item.sessionIds.forEach((sessionId, index) => {
      if (!options.has(sessionId)) {
        options.set(sessionId, item.sessionTitles[index] || sessionId)
      }
    })
  }
  return Array.from(options, ([sessionId, sessionTitle]) => ({ sessionId, sessionTitle }))
}

export function normalizeQueueSessionFilter(
  sessionFilter: string,
  currentSessionId: string | null | undefined,
  sessionOptions: QueueSessionOption[],
): string {
  if (sessionFilter === 'current' && !currentSessionId) return 'all'
  if (sessionFilter === 'all' || sessionFilter === 'current') return sessionFilter
  return sessionOptions.some((option) => option.sessionId === sessionFilter)
    ? sessionFilter
    : 'all'
}

export function filterUnknownQueueItems({
  items,
  searchQuery,
  sessionFilter,
  currentSessionId = null,
  lookupContactName,
}: FilterUnknownQueueItemsArgs): UnknownQueueItem[] {
  const normalizedSearch = searchQuery.trim().toLowerCase()

  return items.filter((item) => {
    const sessionMatch =
      sessionFilter === 'all'
        ? true
        : sessionFilter === 'current'
          ? !!currentSessionId && item.sessionIds.includes(currentSessionId)
          : item.sessionIds.includes(sessionFilter)

    if (!sessionMatch) return false
    if (!normalizedSearch) return true

    const candidateNames = item.candidates
      .map((candidate) => lookupContactName?.(candidate.contactId) ?? candidate.contactId)
      .join(' ')
    const haystack = [
      item.label,
      item.sessionTitle,
      item.sessionTitles.join(' '),
      item.sessionDate,
      item.quote,
      item.totalDuration,
      candidateNames,
    ]
      .join(' ')
      .toLowerCase()

    return haystack.includes(normalizedSearch)
  })
}
