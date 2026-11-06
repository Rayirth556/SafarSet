import type { Batch, BatchItem, DiffCategory, PassengerFlags, PhoneKind, Vehicle } from '@/api/types'

/** Id of the full unresolved-demand panel further down the operator page, which "See options" scrolls to. */
export const UNRESOLVED_ANCHOR = 'unresolved-demand'

/** Categories whose groups end up on a vehicle in this plan. A displaced group counts only when the plan gives it a replacement. */
const SEATED: DiffCategory[] = ['NEWLY_PLACED', 'RESHUFFLED', 'DISPLACED']

export type HelpKind = 'wheelchair' | 'medical' | 'senior' | 'child'
export const HELP_LABEL: Record<HelpKind, string> = { wheelchair: 'Wheelchair', medical: 'Medical need', senior: 'Senior', child: 'Child / pregnant' }
const HELP_ORDER: HelpKind[] = ['wheelchair', 'medical', 'senior', 'child']

/** What a group needs from staff. A group is listed once per kind; the flags say that someone in the group has the need, not how many. */
export function helpKinds(f?: PassengerFlags | null): HelpKind[] {
  if (!f) return []
  const out: HelpKind[] = []
  if (f.wheelchair) out.push('wheelchair')
  if (f.disability) out.push('medical')
  if (f.senior) out.push('senior')
  if (f.child || f.pregnant) out.push('child')
  return out
}

export interface PlanGroup { item: BatchItem; category: DiffCategory; arriveMin: number | null }
export interface VehicleRow {
  vehicleId: string
  groups: PlanGroup[]
  people: number
  /** groups needing each kind of help */
  help: Record<HelpKind, number>
  /** destinations by people, largest first */
  destinations: { name: string; people: number }[]
}

const emptyHelp = (): Record<HelpKind, number> => ({ wheelchair: 0, medical: 0, senior: 0, child: 0 })

/** Who goes on which vehicle in this plan (people, destinations, who needs help), in the order the API lists the vehicles. */
export function planByVehicle(items: Batch['items'], depart: (vehicleId: string) => number): VehicleRow[] {
  const rows = new Map<string, VehicleRow>()
  for (const category of SEATED) {
    for (const item of items?.[category] ?? []) {
      const d = item.detail
      if (category === 'DISPLACED' && !d.replaced) continue                          // lost a seat and gets none: that is "no seat yet", not a vehicle
      const vehicleId = d.vehicle_id as string | undefined
      if (!vehicleId) continue
      let row = rows.get(vehicleId)
      if (!row) rows.set(vehicleId, (row = { vehicleId, groups: [], people: 0, help: emptyHelp(), destinations: [] }))
      row.groups.push({ item, category, arriveMin: typeof d.arrive_min === 'number' ? d.arrive_min : null })
      row.people += item.size
      for (const k of helpKinds(item.flags)) row.help[k]++
      const name = item.dest_name ?? item.dest_place
      const dest = row.destinations.find((x) => x.name === name)
      if (dest) dest.people += item.size
      else row.destinations.push({ name, people: item.size })
    }
  }
  for (const r of rows.values()) r.destinations.sort((a, b) => b.people - a.people || a.name.localeCompare(b.name))
  return [...rows.values()].sort((a, b) => depart(a.vehicleId) - depart(b.vehicleId) || a.vehicleId.localeCompare(b.vehicleId))
}

export interface Fill { used: number; cap: number; confirmed: number; tentative: number; boarded: number }

/**
 * How full a vehicle is at its tightest stretch. A bus or train is as full as its fullest segment, so each pool contributes the segment with
 * the highest load (used / cap); pools of one vehicle are summed. A closed segment (cap 0) is ignored unless the whole pool is closed.
 */
export function vehicleFill(v: Pick<Vehicle, 'pools'>): Fill {
  const total: Fill = { used: 0, cap: 0, confirmed: 0, tentative: 0, boarded: 0 }
  for (const p of v.pools) {
    let best: (typeof p.segments)[number] | null = null
    for (const s of p.segments) {
      if (s.cap <= 0) continue
      const load = (s.confirmed + s.tentative + s.boarded) / s.cap
      if (!best || load > (best.confirmed + best.tentative + best.boarded) / best.cap) best = s
    }
    if (!best) continue
    total.cap += best.cap
    total.confirmed += best.confirmed
    total.tentative += best.tentative
    total.boarded += best.boarded
    total.used += best.confirmed + best.tentative + best.boarded
  }
  return total
}

/** One sentence saying what approving does. `messages` is the exact number of SMS once the server has said it; until then the group count stands in. */
export function consequence(a: { groups: number; people: number; messages: number | null; noSeatPeople: number; kinds?: Record<PhoneKind, number> }): string {
  const sms = a.messages ?? a.groups
  // when the messages are of more than one kind, say what they are: "26 SMS (6 changed journeys, 20 lost seats)"
  const parts = a.kinds ? ([['NEW', 'new journey', 'new journeys'], ['CHANGED', 'changed journey', 'changed journeys'], ['DISPLACED_UNPLACED', 'lost seat', 'lost seats']] as const)
    .filter(([k]) => a.kinds![k] > 0).map(([k, one, many]) => `${a.kinds![k]} ${a.kinds![k] === 1 ? one : many}`) : []
  const detail = parts.length > 1 ? ` (${parts.join(', ')})` : ''
  const sent = `Approving confirms ${a.groups} ${a.groups === 1 ? 'group' : 'groups'} (${a.people} ${a.people === 1 ? 'person' : 'people'}) and sends ${sms} SMS${detail}.`
  if (a.noSeatPeople === 0) return sent
  return `${sent} ${a.noSeatPeople} ${a.noSeatPeople === 1 ? 'person still has' : 'people still have'} no seat.`
}

export { HELP_ORDER }
