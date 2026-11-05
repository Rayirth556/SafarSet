import { describe, expect, it, vi } from 'vitest'
import type { Kpis, SafarEvent, WsMessage } from '@/api/types'
import { classifyEvent, LiveRouter } from './router'

const ev = (seq: number): WsMessage => ({ type: 'event', seq, event: { seq } as SafarEvent })
const snap = (last_seq: number, type: 'snapshot' | 'reset' = 'snapshot'): WsMessage => ({ type, loaded: false, last_seq })

function make() {
  const d = {
    invalidate: vi.fn(), setState: vi.fn(), setKpis: vi.fn(), onEvent: vi.fn(), requestSnapshot: vi.fn(), setSync: vi.fn(),
  }
  return { d, r: new LiveRouter(d) }
}

describe('classifyEvent', () => {
  it('accepts only the next sequence number', () => {
    expect(classifyEvent(5, 6)).toBe('accept')
    expect(classifyEvent(5, 5)).toBe('duplicate')
    expect(classifyEvent(5, 2)).toBe('duplicate')
    expect(classifyEvent(5, 8)).toBe('gap')
    expect(classifyEvent(null, 1)).toBe('gap')
  })
})

describe('LiveRouter', () => {
  it('a snapshot sets the baseline and refetches everything', () => {
    const { d, r } = make()
    r.handle(snap(10))
    expect(r.last).toBe(10)
    expect(d.setState).toHaveBeenCalledOnce()
    expect(d.invalidate).toHaveBeenCalledWith(['all'])
  })

  it('contiguous events pass through and advance the cursor', () => {
    const { d, r } = make()
    r.handle(snap(10))
    r.handle(ev(11)); r.handle(ev(12))
    expect(d.onEvent).toHaveBeenCalledTimes(2)
    expect(r.last).toBe(12)
    expect(d.requestSnapshot).not.toHaveBeenCalled()
  })

  it('ignores duplicates', () => {
    const { d, r } = make()
    r.handle(snap(10)); r.handle(ev(11)); r.handle(ev(11))
    expect(d.onEvent).toHaveBeenCalledOnce()
  })

  it('a gap asks for one snapshot, swallows hints meanwhile, and recovers on the snapshot', () => {
    const { d, r } = make()
    r.handle(snap(10))
    r.handle(ev(13))                       // 11 and 12 missing
    r.handle(ev(14))                       // still gapped: do not ask twice
    expect(d.requestSnapshot).toHaveBeenCalledOnce()
    expect(d.setSync).toHaveBeenLastCalledWith('resyncing')
    d.invalidate.mockClear()
    r.handle({ type: 'invalidate', topics: ['capacity'], last_seq: 14 })
    r.handle({ type: 'kpis', kpis: {} as Kpis, clock: '14:00', clock_min: 840, last_seq: 14 })
    expect(d.invalidate).not.toHaveBeenCalled()
    expect(d.setKpis).not.toHaveBeenCalled()
    r.handle(snap(14))
    expect(r.last).toBe(14)
    expect(d.setSync).toHaveBeenLastCalledWith('live')
    expect(d.invalidate).toHaveBeenCalledWith(['all'])
    r.handle(ev(15))
    expect(d.onEvent).toHaveBeenCalledTimes(1)
  })

  it('a reset (new scenario) may restart the sequence lower', () => {
    const { d, r } = make()
    r.handle(snap(50))
    r.handle(snap(1, 'reset'))
    expect(r.last).toBe(1)
    r.handle(ev(2))
    expect(d.onEvent).toHaveBeenCalledOnce()
    expect(d.requestSnapshot).not.toHaveBeenCalled()
  })

  it('a pong that is ahead of us means we missed events', () => {
    const { d, r } = make()
    r.handle(snap(10))
    r.handle({ type: 'pong', last_seq: 10 })
    expect(d.requestSnapshot).not.toHaveBeenCalled()
    r.handle({ type: 'pong', last_seq: 12 })
    expect(d.requestSnapshot).toHaveBeenCalledOnce()
  })

  it('forwards kpis and hints in normal operation', () => {
    const { d, r } = make()
    r.handle(snap(1))
    d.invalidate.mockClear()
    r.handle({ type: 'kpis', kpis: {} as Kpis, clock: '14:05', clock_min: 845, last_seq: 2 })
    r.handle({ type: 'invalidate', topics: ['batch', 'kpis'], last_seq: 2 })
    expect(d.setKpis).toHaveBeenCalledWith({}, '14:05', 845, 2)
    expect(d.invalidate).toHaveBeenCalledWith(['batch', 'kpis'])
  })

  it('events before any snapshot trigger a snapshot request', () => {
    const { d, r } = make()
    r.handle(ev(1))
    expect(d.requestSnapshot).toHaveBeenCalledOnce()
  })
})
