import type { Alternative, DiffCategory, GroupState } from '@/api/types'

const prettify = (key: string) => {
  const s = key.replace(/_/g, ' ').trim()
  return s.charAt(0).toUpperCase() + s.slice(1)
}

// Readable names for the stub scorer's keys. The real scorer may use other keys: those fall back to a prettified key.
const FACTORS: Record<string, string> = {
  medical_disability: 'Medical need / disability',
  senior_60_plus: 'Senior citizen (60+)',
  child_or_pregnant: 'Children / pregnant',
  hard_deadline: 'Hard deadline',
  reserved_pnr: 'Reserved ticket (PNR)',
  ageing: 'Time waited (ageing)',
  ageing_per_hour: 'Time waited, per hour',
}
export const factorLabel = (k: string) => FACTORS[k] ?? prettify(k)

const CAUSES: Record<string, string> = {
  TRAIN_CANCELLED: 'Train cancelled', TRAIN_DELAYED: 'Train delayed', ROAD_CLOSED: 'Road closed', LOAD_REPORT: 'Load report from the field',
  VACANCY_UPDATE: 'Chart vacancy update', NOSHOWS_REPORTED: 'Second-chart vacancies', PASSENGER_DISPLACED: 'Passenger displaced',
  WEIGHTS_RERUN: 'Weights re-run', MANUAL_REPLAN: 'Manual re-plan', OPERATOR_OVERRIDE: 'Operator override', BUFFER_CHANGED: 'Buffer changed',
  GROUP_SELF_BOARDED: 'Passengers boarded on their own',
}
export const causeLabel = (c: string) => CAUSES[c] ?? prettify(c.toLowerCase())

export const DIFF_LABEL: Record<DiffCategory, string> = {
  DISPLACED: 'Displaced', NEWLY_PLACED: 'Newly placed', RESHUFFLED: 'Reshuffled', PLACED: 'Unchanged', UNRESOLVED: 'Unresolved',
}
export const DIFF_HELP: Record<DiffCategory, string> = {
  DISPLACED: 'lost a seat they held',
  NEWLY_PLACED: 'given a seat for the first time',
  RESHUFFLED: 'moved to another vehicle',
  PLACED: 'keep their seat',
  UNRESOLVED: 'no seat; alternatives offered',
}

export const STATE_LABEL: Record<GroupState, string> = {
  UNAFFECTED: 'Unaffected', UNRESOLVED: 'Unresolved', TENTATIVE: 'Tentative', CONFIRMED: 'Confirmed', BOARDED: 'Boarded',
}

export const ALT_LABEL: Record<Alternative['type'], string> = {
  LATE_ARRIVAL: 'Late arrival', MULTI_LEG: 'Two-leg journey', WAITLIST: 'Waitlist',
}

export const BLOCKING_WHY: Record<string, string> = {
  NO_ALTERNATIVE_WITHIN_TOLERANCE: 'the blocking group has no other option within the arrival tolerance',
  MOVES_AS_MANY_HEADS_AS_PLACED: 'moving the blocking group would displace as many people as it would place',
}

/** Weights as [key, points] pairs, highest points first (ties keep the server's order). */
export const byPoints = <T extends number>(w: Record<string, T>): [string, T][] => Object.entries(w).sort((a, b) => b[1] - a[1])

export const fmtPoints = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1))
