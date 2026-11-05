import { useQuery } from '@tanstack/react-query'
import * as api from '@/api/endpoints'
import type { PassengerQuery } from '@/api/types'
import { qk } from '@/live/invalidation'
import { useAppState } from './useAppState'

/** True once the server has a scenario. Every other query waits for it, so nothing is fetched (or logged as an error) before then. */
export function useLoaded() {
  const { data } = useAppState()
  return data?.loaded === true
}

export const useCapacity = (role: 'ALLOCATION' | 'TRANSFER_LEG' | 'all' = 'ALLOCATION') =>
  useQuery({ queryKey: [...qk.capacity, role], queryFn: () => api.fetchCapacity(role), enabled: useLoaded() })

export const usePassengers = (q: PassengerQuery) =>
  useQuery({ queryKey: [...qk.passengers, q], queryFn: () => api.fetchPassengers(q), enabled: useLoaded(), placeholderData: (prev) => prev })

export const useWhy = (groupId: string | null) =>
  useQuery({ queryKey: [...qk.why, groupId], queryFn: () => api.fetchWhy(groupId!), enabled: useLoaded() && groupId !== null })

export const useUnresolved = () => useQuery({ queryKey: qk.unresolved, queryFn: api.fetchUnresolved, enabled: useLoaded() })
export const usePendingBatch = () => useQuery({ queryKey: [...qk.batch, 'pending'], queryFn: api.fetchPendingBatch, enabled: useLoaded() })
export const useRules = () => useQuery({ queryKey: qk.rules, queryFn: api.fetchRules, enabled: useLoaded() })
export const useEvents = (hideRejected: boolean) =>
  useQuery({
    queryKey: [...qk.events, hideRejected],
    queryFn: () => api.fetchEvents({ tail: true, limit: 300, hide_rejected: hideRejected }),
    enabled: useLoaded(),
    placeholderData: (prev) => prev,
  })

// ------------------------------------------------------------------ field view and phone mock
export const useFieldVehicles = () => useQuery({ queryKey: [...qk.field, 'vehicles'], queryFn: api.fetchFieldVehicles, enabled: useLoaded() })
export const useManifest = (vehicleId: string | null) =>
  useQuery({ queryKey: [...qk.field, 'manifest', vehicleId], queryFn: () => api.fetchManifest(vehicleId!), enabled: useLoaded() && vehicleId !== null })
export const useNotifier = () => useQuery({ queryKey: qk.notifier, queryFn: api.fetchNotifier, enabled: useLoaded() })
export const usePhoneThread = (key: string) =>
  useQuery({ queryKey: [...qk.phone, key], queryFn: () => api.fetchPhoneMessages(key), enabled: useLoaded() })
