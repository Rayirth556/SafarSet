import { QueryClient } from '@tanstack/react-query'
import { ApiError } from '@/api/client'

// Server state is refreshed by the WebSocket's invalidate hints, so nothing goes stale on a timer or on window focus.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: Infinity,
      refetchOnWindowFocus: false,
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
    },
  },
})
