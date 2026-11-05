import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { reportLoad } from '@/api/endpoints'
import type { FieldVehicle, LoadLevel } from '@/api/types'
import { ErrorNote } from '@/components/common/Panels'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

const LEVELS: { level: LoadLevel; label: string; on: string }[] = [
  { level: 'NORMAL', label: 'Normal', on: 'border-confirmed-ink bg-confirmed/15 text-confirmed-ink' },
  { level: 'FULL', label: 'Full', on: 'border-tentative-ink bg-tentative/15 text-tentative-ink' },
  { level: 'OVERCROWDED', label: 'Overcrowded', on: 'border-unresolved-ink bg-unresolved/10 text-unresolved-ink' },
]

/** Stands in for the conductor's ETM. Load reports apply to a vehicle's unreserved pool. */
export function LoadReport({ vehicle }: { vehicle: FieldVehicle }) {
  const qc = useQueryClient()
  const pools = vehicle.pools.filter((p) => p.kind === 'UNRESERVED')
  const [poolId, setPoolId] = useState(pools[0]?.pool_id ?? '')
  const [level, setLevel] = useState<LoadLevel | null>(null)
  const [count, setCount] = useState('')
  const [sent, setSent] = useState<string | null>(null)
  const pool = pools.find((p) => p.pool_id === poolId) ?? pools[0]
  const current = pool?.field_report

  const send = useMutation({
    mutationFn: () => reportLoad(vehicle.vehicle_id, { level: level!, pool_id: pool.pool_id, ...(count.trim() !== '' ? { count: Number(count) } : {}) }),
    onSuccess: () => setSent(`Sent: ${level!.toLowerCase()}${count.trim() ? `, ${count} on board` : ''}. The control room will re-plan anyone allocated here who cannot board.`),
    onSettled: () => { for (const k of ['field', 'capacity', 'passengers', 'batch', 'state']) void qc.invalidateQueries({ queryKey: [k] }) },
  })
  const countBad = count.trim() !== '' && !(Number.isInteger(Number(count)) && Number(count) >= 0)

  return (
    <section className="px-4 py-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">Report actual load</h2>
        <span className="text-sm text-ink-2">feeds the control room</span>
      </div>
      {pools.length === 0 ? (
        <p className="mt-2 rounded-lg bg-secondary px-3 py-3 text-base text-ink-2">
          This vehicle has no unreserved coach, so there is no load to report here. Use the second-chart report below for reserved coaches.
        </p>
      ) : (
        <>
          {pools.length > 1 && (
            <select className="mt-2 h-12 w-full rounded-lg border bg-card px-3 text-base" value={pool.pool_id} onChange={(e) => setPoolId(e.target.value)} aria-label="Coach">
              {pools.map((p) => <option key={p.pool_id} value={p.pool_id}>{p.class} · {p.nominal} seats</option>)}
            </select>
          )}
          {current && (
            <p className="mt-2 text-base text-ink-2" data-testid="current-report">
              Last report: <b className="text-ink">{current.level.toLowerCase()}</b>{current.count != null && <> · <span className="font-mono">{current.count}</span> on board</>}
            </p>
          )}
          <div className="mt-3 grid grid-cols-3 gap-2" role="group" aria-label="Load level">
            {LEVELS.map((l) => (
              <button
                key={l.level}
                aria-pressed={level === l.level}
                onClick={() => { setLevel(l.level); setSent(null) }}
                className={cn('h-14 rounded-lg border-2 bg-card text-base font-semibold', level === l.level ? l.on : 'border-line text-ink')}
              >
                {l.label}
              </button>
            ))}
          </div>
          <label className="mt-3 flex items-center justify-between gap-3">
            <span className="text-base">People on board now <span className="text-ink-2">(optional)</span></span>
            <Input inputMode="numeric" className="h-12 w-24 text-right font-mono text-lg" value={count} onChange={(e) => { setCount(e.target.value); setSent(null) }} aria-label="People on board now" />
          </label>
          <p className="mt-1 text-sm text-ink-2">With no count, the vehicle is treated as exactly full.</p>
          {countBad && <p role="alert" className="text-base text-unresolved-ink">Enter a whole number, or leave it empty.</p>}
          <Button size="lg" className="mt-3 h-12 w-full font-semibold" disabled={!level || countBad || send.isPending} onClick={() => send.mutate()}>
            {send.isPending ? 'Sending…' : 'Send report'}
          </Button>
          {sent && <p role="status" className="mt-2 rounded-lg bg-confirmed/10 px-3 py-2 text-base text-confirmed-ink">{sent}</p>}
          <div className="mt-2"><ErrorNote error={send.error} /></div>
        </>
      )}
    </section>
  )
}
