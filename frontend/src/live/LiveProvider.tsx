import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { AppState, Kpis, WsMessage } from '@/api/types'
import { LiveContext, type LiveStatus } from './context'
import { ALL_KEYS, keysForTopics, qk } from './invalidation'
import { LiveRouter } from './router'
import { wsUrlFor } from '@/api/base'
import { REPLAY } from '@/api/client'


const PING_MS = 20_000
const STALE_MS = 45_000
const BACKOFF_MS = [500, 1000, 2000, 4000, 5000]

function wsUrl() {
  return wsUrlFor('/ws')
}

/** One shared `/ws` connection per page. Feeds the TanStack cache; components only read queries. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [status, setStatus] = useState<LiveStatus>(REPLAY ? 'replay' : 'connecting')
  const [lastSeq, setLastSeq] = useState<number | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (REPLAY) {
      // no socket in the replay: a recorded step change refreshes every screen instead of a server push
      const onStep = () => { for (const queryKey of ALL_KEYS) void qc.invalidateQueries({ queryKey }) }
      window.addEventListener('safarset:replay-step', onStep)
      return () => window.removeEventListener('safarset:replay-step', onStep)
    }
    let closed = false
    let attempt = 0
    let retry: ReturnType<typeof setTimeout> | undefined
    let ping: ReturnType<typeof setInterval> | undefined
    let heard = Date.now()
    let eventsTimer: ReturnType<typeof setTimeout> | undefined

    const router = new LiveRouter({
      invalidate: (topics) => {
        const keys = topics.includes('all') ? ALL_KEYS : keysForTopics(topics)
        for (const queryKey of keys) void qc.invalidateQueries({ queryKey })
      },
      setState: (s: AppState) => qc.setQueryData(qk.state, s),
      setKpis: (kpis: Kpis, clock, clockMin, seq) =>
        qc.setQueryData<AppState>(qk.state, (old) =>
          old && old.loaded ? { ...old, kpis, clock, clock_min: clockMin, last_seq: seq } : old),
      // the event log refetches its tail, at most once per burst (approving a batch emits hundreds of events at once)
      onEvent: () => {
        if (eventsTimer) return
        eventsTimer = setTimeout(() => { eventsTimer = undefined; void qc.invalidateQueries({ queryKey: qk.events }) }, 200)
      },
      requestSnapshot: () => wsRef.current?.readyState === WebSocket.OPEN && wsRef.current.send(JSON.stringify({ type: 'snapshot' })),
      setSync: (s) => setStatus(s),
    })

    const connect = () => {
      if (closed) return
      const ws = new WebSocket(wsUrl())
      wsRef.current = ws
      router.reset()
      ws.onopen = () => { attempt = 0; heard = Date.now() }
      ws.onmessage = (e) => {
        heard = Date.now()
        router.handle(JSON.parse(e.data) as WsMessage)
        setLastSeq(router.last)
      }
      ws.onclose = () => {
        if (closed || wsRef.current !== ws) return
        setStatus('reconnecting')
        retry = setTimeout(connect, BACKOFF_MS[Math.min(attempt++, BACKOFF_MS.length - 1)])
      }
      ws.onerror = () => ws.close()
    }

    // deferred so React StrictMode's throw-away first mount never opens (and immediately closes) a socket
    const start = setTimeout(connect, 0)
    ping = setInterval(() => {
      const ws = wsRef.current
      if (!ws || ws.readyState !== WebSocket.OPEN) return
      if (Date.now() - heard > STALE_MS) return ws.close()      // dead connection: onclose reconnects
      ws.send(JSON.stringify({ type: 'ping' }))
    }, PING_MS)

    return () => {
      closed = true
      clearTimeout(start)
      clearTimeout(eventsTimer)
      clearTimeout(retry)
      clearInterval(ping)
      wsRef.current?.close()
    }
  }, [qc])

  const value = useMemo(() => ({ status, lastSeq }), [status, lastSeq])
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>
}
