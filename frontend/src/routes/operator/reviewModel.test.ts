import { describe, expect, it } from 'vitest'
import type { BatchItem, PassengerFlags, Pool, Segment } from '@/api/types'
import { consequence, helpKinds, planByVehicle, vehicleFill } from './reviewModel'

const none: PassengerFlags = { senior: false, child: false, pregnant: false, disability: false, wheelchair: false, deadline: null }
const item = (group_id: string, size: number, detail: BatchItem['detail'], flags: Partial<PassengerFlags> = {}, dest = 'Avadi'): BatchItem =>
  ({ group_id, pnr: null, size, class: 'UR', dest_place: dest.toUpperCase(), dest_name: dest, flags: { ...none, ...flags }, detail })
const placed = (vehicle_id: string, arrive_min = 960) => ({ vehicle_id, pool_id: `${vehicle_id}:UR`, arrive_min, class_step: 'SAME_CLASS' })
const dep: Record<string, number> = { BUS_A: 880, BUS_B: 905, TRAIN: 930 }
const departOf = (id: string) => dep[id] ?? 0

describe('helpKinds', () => {
  it('lists each need once and folds child and pregnant together', () => {
    expect(helpKinds({ ...none, wheelchair: true, senior: true })).toEqual(['wheelchair', 'senior'])
    expect(helpKinds({ ...none, child: true, pregnant: true })).toEqual(['child'])
    expect(helpKinds(none)).toEqual([])
  })
})

describe('planByVehicle', () => {
  const rows = planByVehicle({
    NEWLY_PLACED: [item('G1', 3, placed('TRAIN'), { wheelchair: true }), item('G2', 2, placed('BUS_B')), item('G3', 1, placed('BUS_A'), { senior: true }, 'Poonamallee')],
    RESHUFFLED: [item('G4', 4, { ...placed('BUS_A'), forced: false }, { senior: true, child: true }, 'Poonamallee')],
    DISPLACED: [item('G5', 5, { replaced: true, ...placed('BUS_A') }), item('G6', 7, { replaced: false })],
  }, departOf)

  it('lists vehicles by departure time, earliest first', () => expect(rows.map((r) => r.vehicleId)).toEqual(['BUS_A', 'BUS_B', 'TRAIN']))
  it('counts people, not groups, and includes reshuffled and replaced groups', () => {
    const a = rows[0]
    expect(a.groups.map((g) => g.item.group_id)).toEqual(['G3', 'G4', 'G5'])
    expect(a.people).toBe(1 + 4 + 5)
  })
  it('leaves out a displaced group that gets no replacement: it has no vehicle', () => {
    expect(rows.flatMap((r) => r.groups.map((g) => g.item.group_id))).not.toContain('G6')
  })
  it('counts the groups that need each kind of help', () => {
    expect(rows[0].help).toEqual({ wheelchair: 0, medical: 0, senior: 2, child: 1 })
    expect(rows[2].help.wheelchair).toBe(1)
  })
  it('orders destinations by people, largest first', () => expect(rows[0].destinations).toEqual([{ name: 'Avadi', people: 5 }, { name: 'Poonamallee', people: 5 }]))
  it('copes with no items', () => expect(planByVehicle(undefined, departOf)).toEqual([]))
})

const seg = (o: Partial<Segment>): Segment => ({ seg_idx: 0, from_stop: 'A', to_stop: 'B', cap: 10, confirmed: 0, boarded: 0, tentative: 0, free: 10, ...o })
const pool = (segments: Segment[]): Pool =>
  ({ pool_id: 'P', kind: 'UNRESERVED', class: 'UR', coaches: 1, nominal: 40, capacity_label: '', buffer_mode: null, buffer_pct: null, formula: '', walkon_expected: 0, field_report: null, segments })

describe('vehicleFill', () => {
  it('is as full as the fullest stretch', () => {
    const f = vehicleFill({ pools: [pool([seg({ confirmed: 2 }), seg({ seg_idx: 1, confirmed: 6, tentative: 3 }), seg({ seg_idx: 2, confirmed: 1 })])] })
    expect(f).toMatchObject({ used: 9, cap: 10, confirmed: 6, tentative: 3 })
  })
  it('ignores a closed stretch and sums the pools of one vehicle', () => {
    const f = vehicleFill({ pools: [pool([seg({ cap: 0 }), seg({ seg_idx: 1, cap: 20, confirmed: 5 })]), pool([seg({ cap: 30, tentative: 4 })])] })
    expect(f).toMatchObject({ used: 9, cap: 50 })
  })
  it('a vehicle with every stretch closed has no capacity', () => expect(vehicleFill({ pools: [pool([seg({ cap: 0 })])] })).toMatchObject({ used: 0, cap: 0 }))
})

describe('consequence', () => {
  it('says what approving does, using the server count of SMS when it has one', () => {
    expect(consequence({ groups: 207, people: 273, messages: 207, noSeatPeople: 0 })).toBe('Approving confirms 207 groups (273 people) and sends 207 SMS.')
  })
  it('falls back to one SMS per group until the count arrives, and warns about people with no seat', () => {
    expect(consequence({ groups: 1, people: 1, messages: null, noSeatPeople: 27 })).toBe('Approving confirms 1 group (1 person) and sends 1 SMS. 27 people still have no seat.')
    expect(consequence({ groups: 6, people: 9, messages: 26, noSeatPeople: 1 })).toContain('1 person still has no seat.')
  })
  it('names the kinds of message when there is more than one, and stays quiet when there is only one', () => {
    const mixed = { NEW: 0, CHANGED: 6, DISPLACED_UNPLACED: 20 }
    expect(consequence({ groups: 6, people: 9, messages: 26, noSeatPeople: 0, kinds: mixed })).toBe('Approving confirms 6 groups (9 people) and sends 26 SMS (6 changed journeys, 20 lost seats).')
    expect(consequence({ groups: 207, people: 273, messages: 207, noSeatPeople: 0, kinds: { NEW: 207, CHANGED: 0, DISPLACED_UNPLACED: 0 } })).toBe('Approving confirms 207 groups (273 people) and sends 207 SMS.')
    expect(consequence({ groups: 1, people: 1, messages: 2, noSeatPeople: 0, kinds: { NEW: 1, CHANGED: 1, DISPLACED_UNPLACED: 0 } })).toContain('(1 new journey, 1 changed journey)')
  })
})
