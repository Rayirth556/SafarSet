import type { AppState, Kpis, SafarEvent, Topic, WsMessage } from '@/api/types'

/** What the router needs from the outside world; the real implementation talks to a WebSocket and a QueryClient. */
export interface LiveDeps {
  invalidate(topics: readonly Topic[]): void
  setState(state: AppState): void
  setKpis(kpis: Kpis, clock: string, clockMin: number, lastSeq: number): void
  onEvent(event: SafarEvent): void
  requestSnapshot(): void
  setSync(s: 'live' | 'resyncing'): void
}

export type EventVerdict = 'accept' | 'duplicate' | 'gap'

/** Event sequence numbers are contiguous. `last` is null until the first snapshot has been seen. */
export function classifyEvent(last: number | null, seq: number): EventVerdict {
  if (last === null) return 'gap'
  if (seq <= last) return 'duplicate'
  return seq === last + 1 ? 'accept' : 'gap'
}

/** Turns stream messages into cache updates and invalidations, and detects sequence gaps. No sockets, no React: unit-testable. */
export class LiveRouter {
  last: number | null = null
  private resyncing = false

  private readonly d: LiveDeps

  constructor(deps: LiveDeps) {
    this.d = deps
  }

  /** A new connection starts with no baseline: the server sends a snapshot first. */
  reset() {
    this.last = null
    this.resyncing = false
  }

  handle(msg: WsMessage) {
    switch (msg.type) {
      case 'snapshot':
      case 'reset': {
        // a snapshot or a new scenario is a fresh baseline; after a reset the sequence may restart lower, so trust the message
        const { type: _t, ...state } = msg
        this.last = msg.last_seq
        this.resyncing = false
        this.d.setState(state as AppState)
        this.d.invalidate(['all'])
        this.d.setSync('live')
        return
      }
      case 'event': {
        const v = classifyEvent(this.last, msg.seq)
        if (v === 'duplicate') return
        if (v === 'gap') return this.resync()
        this.last = msg.seq
        this.d.onEvent(msg.event)
        return
      }
      case 'kpis':
        if (this.resyncing) return
        this.d.setKpis(msg.kpis, msg.clock, msg.clock_min, msg.last_seq)
        return
      case 'invalidate':
        if (this.resyncing) return                 // the pending snapshot invalidates everything anyway
        this.d.invalidate(msg.topics)
        return
      case 'pong':
        if (this.last !== null && msg.last_seq > this.last) this.resync()
        return
      default:
        return
    }
  }

  private resync() {
    if (this.resyncing) return
    this.resyncing = true
    this.d.setSync('resyncing')
    this.d.requestSnapshot()
  }
}
