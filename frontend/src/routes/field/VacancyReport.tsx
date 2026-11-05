import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { reportVacancy } from '@/api/endpoints'
import type { FieldVehicle } from '@/api/types'
import { ErrorNote } from '@/components/common/Panels'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useCapacity } from '@/hooks/queries'

const select = 'mt-1 h-12 w-full rounded-lg border bg-card px-3 text-base'

/**
 * TTE hand-held terminal: second-chart vacancies on a reserved coach. The railway prepares its final chart about 30 min before
 * departure. The value is the number of seats open on the chart for the chosen stretch; it replaces what was open before.
 */
export function VacancyReport({ vehicle }: { vehicle: FieldVehicle }) {
  const qc = useQueryClient()
  const { data: capacity } = useCapacity('ALLOCATION')
  const reserved = vehicle.pools.filter((p) => p.kind === 'RESERVED')
  const stops = capacity?.find((v) => v.vehicle_id === vehicle.vehicle_id)?.stops ?? []
  const [poolId, setPoolId] = useState('')
  const [from, setFrom] = useState('0')
  const [to, setTo] = useState('')
  const [seats, setSeats] = useState('')
  const [done, setDone] = useState<string | null>(null)

  const pool = reserved.find((p) => p.pool_id === (poolId || reserved[0]?.pool_id))
  const segs = capacity?.find((v) => v.vehicle_id === vehicle.vehicle_id)?.pools.find((p) => p.pool_id === pool?.pool_id)?.segments ?? []
  const toIdx = to === '' ? stops.length - 1 : Number(to)
  const inRange = segs.filter((s) => s.seg_idx >= Number(from) && s.seg_idx < toIdx)
  const open = inRange.length ? { min: Math.min(...inRange.map((s) => s.cap)), max: Math.max(...inRange.map((s) => s.cap)) } : null
  const n = Number(seats)
  const bad = seats.trim() === '' || !Number.isInteger(n) || n < 0 ? 'Enter the number of vacant seats.'
    : pool && n > pool.nominal ? `This class has ${pool.nominal} seats in total.`
    : toIdx <= Number(from) ? 'Choose a later stop to end at.' : null
  const lowers = open !== null && bad === null && n < open.max

  const send = useMutation({
    mutationFn: () => reportVacancy(vehicle.vehicle_id, { pool_id: pool!.pool_id, from_seg: Number(from), to_seg: toIdx, vacancy: n }),
    onSuccess: (r) => setDone(`Reported ${n} vacant on ${pool!.class}, ${stops[Number(from)]} to ${stops[toIdx]}.${r.batch_id ? ` The control room has a new plan to approve (${r.batch_id}).` : ''}`),
    onSettled: () => { for (const k of ['field', 'capacity', 'passengers', 'batch', 'state']) void qc.invalidateQueries({ queryKey: [k] }) },
  })

  return (
    <section className="px-4 py-4" data-testid="vacancy-report">
      <h2 className="text-lg font-semibold">Second-chart vacancies</h2>
      <p className="text-sm text-ink-2">TTE report from the final chart, prepared about 30 min before departure.</p>
      {reserved.length === 0 ? (
        <p className="mt-2 rounded-lg bg-secondary px-3 py-3 text-base text-ink-2">This vehicle has no reserved coaches.</p>
      ) : (
        <div className="mt-2 space-y-3">
          <label className="block text-base">Class (all coaches)
            <select className={select} value={pool?.pool_id ?? ''} onChange={(e) => { setPoolId(e.target.value); setDone(null) }}>
              {reserved.map((p) => <option key={p.pool_id} value={p.pool_id}>{p.class} · all {p.nominal} seats in class</option>)}
            </select>
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-base">From
              <select className={select} value={from} onChange={(e) => { setFrom(e.target.value); setDone(null) }}>
                {stops.slice(0, -1).map((s, i) => <option key={i} value={i}>{s}</option>)}
              </select>
            </label>
            <label className="block text-base">To
              <select className={select} value={toIdx} onChange={(e) => { setTo(e.target.value); setDone(null) }}>
                {stops.map((s, i) => (i > Number(from) ? <option key={i} value={i}>{s}</option> : null))}
              </select>
            </label>
          </div>
          {open && <p className="text-sm text-ink-2">Open for allocation now on this stretch: <span className="font-mono">{open.min === open.max ? open.min : `${open.min}–${open.max}`}</span> seats.</p>}
          <label className="flex items-center justify-between gap-3 text-base">Seats vacant on the chart
            <Input inputMode="numeric" className="h-12 w-24 text-right font-mono text-lg" value={seats} onChange={(e) => { setSeats(e.target.value); setDone(null) }} aria-label="Seats vacant on the chart" />
          </label>
          {lowers && <p role="alert" className="rounded-lg bg-tentative/10 px-3 py-2 text-base text-tentative-ink">This is lower than what is open now. Groups that no longer fit are displaced and re-planned.</p>}
          <Button size="lg" className="h-12 w-full font-semibold" disabled={!!bad || send.isPending} title={bad ?? undefined} onClick={() => send.mutate()}>
            {send.isPending ? 'Sending…' : 'Send second-chart report'}
          </Button>
          {done && <p role="status" className="rounded-lg bg-confirmed/10 px-3 py-2 text-base text-confirmed-ink">{done}</p>}
          <ErrorNote error={send.error} />
        </div>
      )}
    </section>
  )
}
