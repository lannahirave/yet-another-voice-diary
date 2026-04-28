export const queryKeys = {
  contacts: {
    all: ['contacts'] as const,
    list: () => ['contacts', 'list'] as const,
    utterancesRoot: () => ['contacts', 'utterances'] as const,
    utterances: (contactId: string) => ['contacts', 'utterances', contactId] as const,
  },
  queue: {
    all: ['queue'] as const,
    listRoot: () => ['queue', 'list'] as const,
    list: (params?: { limit?: number; offset?: number }) =>
      ['queue', 'list', params ?? {}] as const,
    count: () => ['queue', 'count'] as const,
  },
  sessions: {
    all: ['sessions'] as const,
    list: () => ['sessions', 'list'] as const,
    utterancesRoot: () => ['sessions', 'utterances'] as const,
    utterances: (sessionId: string) => ['sessions', 'utterances', sessionId] as const,
  },
  search: {
    all: ['search'] as const,
    results: (params: { q: string; language?: string; limit?: number }) =>
      ['search', 'results', params] as const,
  },
  config: {
    all: ['config'] as const,
    current: () => ['config', 'current'] as const,
    storage: () => ['config', 'storage'] as const,
  },
} as const
