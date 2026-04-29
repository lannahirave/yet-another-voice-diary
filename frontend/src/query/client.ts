import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      gcTime: 5 * 60_000,
      staleTime: Infinity,
      refetchOnWindowFocus: false,
    },
  },
})
