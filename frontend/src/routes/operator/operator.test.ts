import { describe, expect, it } from 'vitest'
import type { SafarEvent, Segment } from '@/api/types'
import { barShares, mergeRuns } from './CapacityPanel'
import { eventSummary, toRows } from './EventLog'
import { parseDraft } from './WeightsEditor'

const seg = (o: Partial<Segment>): Segment => ({ seg_idx: 0, from_stop: 'A', to_stop: 'B', cap: 10, confirmed: 0, boarded: 0, tentative: 0, free: 10, ...o })
const ev = (seq: number, type: string, payload: Record<string, unknown> = {}): SafarEvent =>
  ({ seq, type, payload, actor: 'sim', ts_sim: 840 + seq, ts_wall: '', causation_seq: null, rejected: type === 'COMMAND_REJECTED' })

describe('barShares', () => {
  it('splits a segment into shares of its capacity', () => {
    const b = barShares(seg({ confirmed: 5, tentative: 3, boarded: 2, free: 0 }))
    expect(b.confirmed).toBe(50); expect(b.tentative).toBe(30); expect(b.boarded).toBe(20)
  })
  it('never exceeds 100% even if the numbers do', () => {
    const b = barShares(seg({ cap: 10, confirmed: 12, tentative: 6, boarded: 2 }))
    expect(b.confirmed + b.tentative + b.boarded).toBeCloseTo(100)
  })
  it('a closed segment (cap 0) has an empty bar', () => {
    expect(barShares(seg({ cap: 0 }))).toMatchObject({ closed: true, confirmed: 0, tentative: 0, boarded: 0 })
  })
})

describe('mergeRuns', () => {
  it('merges consecutive identical segments and keeps the end stops', () => {
    const runs = mergeRuns([
      seg({ seg_idx: 0, from_stop: 'A', to_stop: 'B', confirmed: 4 }),
      seg({ seg_idx: 1, from_stop: 'B', to_stop: 'C', confirmed: 4 }),
      seg({ seg_idx: 2, from_stop: 'C', to_stop: 'D', confirmed: 7 }),
    ])
    expect(runs.map((r) => [r.from, r.to, r.count])).toEqual([['A', 'C', 2], ['C', 'D', 1]])
  })
})

describe('event log', () => {
  it('collapses consecutive SMS events into one row, newest first', () => {
    const rows = toRows([ev(1, 'TRAIN_CANCELLED', { vehicle_id: 'T1' }), ev(2, 'SMS_SENT', { group_id: 'G1' }), ev(3, 'SMS_SENT', { group_id: 'G2' }), ev(4, 'BATCH_APPROVED', { batch_id: 'B1' })])
    expect(rows.map((r) => r.text)).toEqual(['Batch B1 approved', '2 passenger messages sent', 'T1 cancelled'])
  })
  it('falls back to the type name for an unknown event', () => {
    expect(eventSummary(ev(1, 'SOMETHING_NEW'))).toBe('Something new')
  })
})

describe('parseDraft', () => {
  it('keeps every key as a number', () => expect(parseDraft({ a: '40', b: '2.5' })).toEqual({ weights: { a: 40, b: 2.5 } }))
  it('rejects blanks and negatives', () => {
    expect(parseDraft({ senior_60_plus: '' })).toHaveProperty('error')
    expect(parseDraft({ a: '-1' })).toHaveProperty('error')
  })
})

import { byPoints } from '@/lib/labels'
import { displayNames } from '@/lib/vehicles'

describe('displayNames', () => {
  const v = (vehicle_id: string, name: string | null) => ({ vehicle_id, name, label: '' })
  it('numbers vehicles that share a name, specials in id order', () => {
    const n = displayNames([v('BUS-SPL-04', 'MTC 120 R1'), v('BUS-SPL-02', 'MTC 120 R1'), v('TRAIN-12607', 'Lalbagh Express')])
    expect(n.get('BUS-SPL-02')).toBe('MTC 120 R1 · Special 1/2')
    expect(n.get('BUS-SPL-04')).toBe('MTC 120 R1 · Special 2/2')
    expect(n.get('TRAIN-12607')).toBe('Lalbagh Express')
  })
  it('does not number transfer-leg services, and does not count them when numbering a special', () => {
    const leg = (id: string) => ({ vehicle_id: id, name: 'MTC 54', label: '', role: 'TRANSFER_LEG' as const })
    const n = displayNames([{ vehicle_id: 'BUS-SPL-01', name: 'MTC 54', label: '', role: 'ALLOCATION' as const }, leg('BUS-REG-1'), leg('BUS-REG-2')])
    expect(n.get('BUS-SPL-01')).toBe('MTC 54')
    expect(n.get('BUS-REG-1')).toBe('MTC 54')
  })
  it('numbers non-special duplicates without the word Special, and falls back to the id when unnamed', () => {
    const n = displayNames([v('BUS-REG-1', 'MTC 54'), v('BUS-REG-2', 'MTC 54'), v('X-9', null)])
    expect(n.get('BUS-REG-2')).toBe('MTC 54 · 2/2')
    expect(n.get('X-9')).toBe('X-9')
  })
})

describe('byPoints', () => {
  it('orders highest points first, not alphabetically', () => {
    expect(byPoints({ a_low: 6, z_high: 40, m_mid: 25 }).map(([k]) => k)).toEqual(['z_high', 'm_mid', 'a_low'])
  })
})

import { showLangBadge } from '@/routes/phone/PhonePage'

describe('phone language badge', () => {
  it('hides the badge for English when the mock is English-only, but never hides Tamil', () => {
    expect(showLangBadge(true, 'en')).toBe(false)
    expect(showLangBadge(true, 'ta')).toBe(true)
    expect(showLangBadge(false, 'en')).toBe(true)
  })
})

import { isUpdate } from '@/routes/phone/PhonePage'

describe('phone update highlighting', () => {
  it('highlights messages that change an earlier plan, not new ones or old logs without a kind', () => {
    expect(isUpdate('CHANGED')).toBe(true)
    expect(isUpdate('DISPLACED_UNPLACED')).toBe(true)
    expect(isUpdate('NEW')).toBe(false)
    expect(isUpdate(null)).toBe(false)
  })
})

import { fitScale } from '@/routes/demo/DemoPage'

describe('demo page scale', () => {
  it('fits the canvas under the header at projector sizes', () => {
    for (const [w, h] of [[1920, 1080], [1280, 720]]) {
      const s = fitScale(w, h)
      expect(s * 2186).toBeLessThanOrEqual(w + 0.001)          // canvas width
      expect(56 + s * 1144).toBeLessThanOrEqual(h + 0.001)     // header + canvas height
    }
  })
})


describe('extra vehicle in the event log', () => {
  it('names the vehicle and when it leaves', () => {
    const e = ev(1, 'VEHICLE_DEPLOYED', { vehicle: { vehicle_id: 'BUS-SPL-05', name: 'MTC 54', depart_min: 920 } })
    expect(eventSummary(e)).toBe('Extra MTC 54 (BUS-SPL-05) deployed, departs 15:20')
  })
})
