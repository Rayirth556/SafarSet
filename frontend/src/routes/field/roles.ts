import type { FieldVehicle } from '@/api/types'

/** The two field roles. A conductor works a bus; a TTE (ticket examiner) works a train. */
export type FieldRole = 'conductor' | 'tte'

export const ROLE_LABEL: Record<FieldRole, string> = { conductor: 'Conductor (bus)', tte: 'TTE (train)' }
const ROLE_MODE: Record<FieldRole, string> = { conductor: 'BUS', tte: 'TRAIN' }

export const parseRole = (s: string | null): FieldRole | null => (s === 'conductor' || s === 'tte' ? s : null)

/** The role that works a vehicle, so a link that names only a vehicle (the /demo field pane) still opens the right view. */
export const roleOfMode = (mode: string): FieldRole | null => (mode === 'BUS' ? 'conductor' : mode === 'TRAIN' ? 'tte' : null)

/** The vehicles a role works, in the order the API lists them. */
export const vehiclesFor = (role: FieldRole | null, vehicles: FieldVehicle[]) =>
  role ? vehicles.filter((v) => v.mode === ROLE_MODE[role]) : []
