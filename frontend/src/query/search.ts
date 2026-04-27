import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { searchUtterances } from '../api/search'
import { queryKeys } from './keys'

export function useSearchResultsQuery(
  query: string,
  filters: { language?: string; limit?: number; sessionId?: string } = {},
) {
  const trimmedQuery = query.trim()

  return useQuery({
    queryKey: queryKeys.search.results({
      q: trimmedQuery,
      language: filters.language,
      limit: filters.limit,
    }),
    queryFn: () => searchUtterances(trimmedQuery, filters),
    enabled: trimmedQuery.length > 0,
    placeholderData: keepPreviousData,
  })
}
