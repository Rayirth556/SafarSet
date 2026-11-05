import { useQuery } from '@tanstack/react-query'
import { fetchState } from '@/api/endpoints'
import { qk } from '@/live/invalidation'

/** Clock, banner, KPIs, pending-batch summary and sim params. Kept fresh by the WebSocket (snapshot, kpis message, hints). */
export function useAppState() {
  return useQuery({ queryKey: qk.state, queryFn: fetchState })
}
