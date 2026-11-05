import { useCallback, useState } from 'react'

export interface LogEntry { id: number; at: string; text: string; ok: boolean }

/**
 * Runs a demo-control action, keeps a local "injected events" log for this session, and exposes the last error.
 * The log is the UI's own record of what was pressed and what the server answered; it is not stored anywhere.
 */
export function useActions(clock: string | null) {
  const [log, setLog] = useState<LogEntry[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  const run = useCallback(async <T,>(label: string, fn: () => Promise<T>, describe?: (r: T) => string) => {
    setBusy(true)
    setError(null)
    try {
      const r = await fn()
      setLog((l) => [{ id: Date.now() + Math.random(), at: clock ?? '--:--', text: label ? (describe ? `${label}: ${describe(r)}` : label) : describe ? describe(r) : '', ok: true }, ...l].slice(0, 30))
      return r
    } catch (e) {
      setError(e as Error)
      setLog((l) => [{ id: Date.now() + Math.random(), at: clock ?? '--:--', text: `${label || 'Timeline step'}: refused. ${(e as Error).message}`, ok: false }, ...l].slice(0, 30))
      return undefined
    } finally {
      setBusy(false)
    }
  }, [clock])

  return { log, busy, error, run }
}

export type Act = ReturnType<typeof useActions>
