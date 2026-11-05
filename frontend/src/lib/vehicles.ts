import { useMemo } from 'react'
import type { Vehicle } from '@/api/types'
import { useCapacity } from '@/hooks/queries'

/** Passenger-facing name of a vehicle, before disambiguation. */
export const vehicleName = (v: Pick<Vehicle, 'name' | 'label' | 'vehicle_id'>) => v.name ?? v.vehicle_id

/**
 * Display names that are unique. Vehicles that share a name get a suffix, in vehicle-id order:
 * two dispatched specials of route "MTC 120 R1" become "MTC 120 R1 · Special 1/2" and "· Special 2/2".
 * Pure, so it is unit-tested.
 */
export function displayNames(vehicles: (Pick<Vehicle, 'name' | 'label' | 'vehicle_id'> & { role?: Vehicle['role'] })[]): Map<string, string> {
  // Only dispatched vehicles are numbered. Regular services used as transfer legs share a route name by the dozen ("MTC 54" x 34 trips),
  // and a number on those would only be noise (and would wrongly number a special among them).
  const byName = new Map<string, string[]>()
  for (const v of vehicles) if (v.role !== 'TRANSFER_LEG') byName.set(vehicleName(v), [...(byName.get(vehicleName(v)) ?? []), v.vehicle_id])
  const out = new Map<string, string>()
  for (const v of vehicles) {
    const name = vehicleName(v)
    const ids = [...(byName.get(name) ?? [])].sort()
    if (v.role === 'TRANSFER_LEG' || ids.length === 1) { out.set(v.vehicle_id, name); continue }
    const special = /SPL/i.test(v.vehicle_id)
    out.set(v.vehicle_id, `${name} · ${special ? 'Special ' : ''}${ids.indexOf(v.vehicle_id) + 1}/${ids.length}`)
  }
  return out
}

export type DisplayVehicle = Vehicle & { display: string }

/** vehicle_id -> vehicle with a unique `display` name, over every vehicle including transfer legs. */
export function useVehicleIndex() {
  const { data } = useCapacity('all')
  return useMemo(() => {
    const names = displayNames(data ?? [])
    return new Map((data ?? []).map((v) => [v.vehicle_id, { ...v, display: names.get(v.vehicle_id) ?? vehicleName(v) }]))
  }, [data])
}

export const nameOf = (index: Map<string, DisplayVehicle>, id: string | undefined | null) => {
  if (!id) return '—'
  return index.get(id)?.display ?? id
}

/** "TRAIN-12607:2S" -> "2S" */
export const poolClass = (poolId: string) => poolId.split(':').pop() ?? poolId

/** "CENTRAL" -> "Central" */
export const titleCase = (s: string) => s.toLowerCase().replace(/(^|[\s_-])(\w)/g, (_, a, b) => a.replace('_', ' ') + b.toUpperCase())
