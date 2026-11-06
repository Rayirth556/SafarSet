import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { qk } from '@/live/invalidation'
import { wsUrlFor } from '@/api/base'

const BACKOFF_MS = [500, 1000, 2000, 4000, 5000]

/**
 * `WS /ws/phone/{key}`: the server pushes each SMS to the phone it belongs to. The thread itself is read over REST (the single source
 * of truth); a push, and every (re)connect, just makes that query refetch, so history and pushes can never double up.
 */
export function usePhoneSocket(key: string, enabled: boolean) {
  const qc = useQueryClient()
  useEffect(() => {
    if (!enabled) return
    let closed = false
    let attempt = 0
    let ws: WebSocket | undefined
    let retry: ReturnType<typeof setTimeout> | undefined
    const refetch = () => void qc.invalidateQueries({ queryKey: [...qk.phone, key] })

    const connect = () => {
      if (closed) return
      ws = new WebSocket(wsUrlFor(`/ws/phone/${encodeURIComponent(key)}`))
      ws.onopen = () => { attempt = 0 }
      ws.onmessage = refetch                       // 'history' on connect, 'sms' on every new message
      ws.onclose = () => { if (!closed) retry = setTimeout(connect, BACKOFF_MS[Math.min(attempt++, BACKOFF_MS.length - 1)]) }
      ws.onerror = () => ws?.close()
    }
    const start = setTimeout(connect, 0)           // deferred so StrictMode's throw-away mount never opens a socket
    return () => {
      closed = true
      clearTimeout(start)
      clearTimeout(retry)
      ws?.close()
    }
  }, [qc, key, enabled])
}
