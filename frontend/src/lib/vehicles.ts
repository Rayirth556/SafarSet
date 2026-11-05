import { useMemo } from 'react'
import type { Vehicle } from '@/api/types'
import { useCapacity } from '@/hooks/queries'

/** Passenger-facing name of a vehicle. Two vehicles can share a name (two "MTC 120 R1"), so pair it with the id where it matters. */
export const vehicleName = (v: Pick<Vehicle, 'name' | 'label' | 'vehicle_id'>) => v.name ?? v.vehicle_id

/** vehicle_id -> vehicle, over every vehicle including transfer legs. */
export function useVehicleIndex() {
  const { data } = useCapacity('all')
  return useMemo(() => new Map((data ?? []).map((v) => [v.vehicle_id, v])), [data])
}

export const nameOf = (index: Map<string, Vehicle>, id: string | undefined | null) => {
  if (!id) return '—'
  const v = index.get(id)
  return v ? vehicleName(v) : id
}

/** "TRAIN-12607:2S" -> "2S" */
export const poolClass = (poolId: string) => poolId.split(':').pop() ?? poolId

/** "CENTRAL" -> "Central" */
export const titleCase = (s: string) => s.toLowerCase().replace(/(^|[\s_-])(\w)/g, (_, a, b) => a.replace('_', ' ') + b.toUpperCase())
