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
