import type { Pool, Segment, Vehicle } from '@/api/types'
import { Card, ErrorNote, Loading } from '@/components/common/Panels'
import { Pill } from '@/components/common/StatusChip'
import { useCapacity } from '@/hooks/queries'
import { nameOf, useVehicleIndex } from '@/lib/vehicles'
import { cn } from '@/lib/utils'

/** Shares of a segment, as percentages of its capacity. They are scaled down if they ever summed past the capacity, so a bar cannot exceed 100%. */
export function barShares(s: Pick<Segment, 'cap' | 'boarded' | 'confirmed' | 'tentative'>) {
  const used = s.boarded + s.confirmed + s.tentative
  if (s.cap <= 0) return { boarded: 0, confirmed: 0, tentative: 0, used, closed: true }
  const scale = used > s.cap ? s.cap / used : 1
  const pct = (n: number) => (n * scale * 100) / s.cap
  return { boarded: pct(s.boarded), confirmed: pct(s.confirmed), tentative: pct(s.tentative), used, closed: false }
}

interface Run { from: string; to: string; count: number; seg: Segment }

/** Merge consecutive segments with identical load (a bus has ~30 stops, most of them the same). */
export function mergeRuns(segments: Segment[]): Run[] {
  const runs: Run[] = []
  for (const s of segments) {
    const last = runs.at(-1)
    if (last && last.seg.cap === s.cap && last.seg.confirmed === s.confirmed && last.seg.boarded === s.boarded && last.seg.tentative === s.tentative) {
      last.to = s.to_stop
      last.count++
    } else runs.push({ from: s.from_stop, to: s.to_stop, count: 1, seg: s })
  }
  return runs
}

function Bar({ seg }: { seg: Segment }) {
  const b = barShares(seg)
  const label = `${b.used} of ${seg.cap} seats: ${seg.confirmed} confirmed, ${seg.tentative} tentative, ${seg.boarded} boarded, ${Math.max(0, seg.free)} free`
  return (
    <div role="img" aria-label={label} title={label} className="flex h-4 w-full overflow-hidden rounded-sm bg-secondary ring-1 ring-line">
      <div className="h-full bg-boarded" style={{ width: `${b.boarded}%` }} />
      <div className="h-full bg-confirmed" style={{ width: `${b.confirmed}%` }} />
      <div className="h-full bg-tentative ring-1 ring-inset ring-tentative-ink" style={{ width: `${b.tentative}%` }} />
    </div>
  )
}

function FieldFlag({ pool }: { pool: Pool }) {
  const r = pool.field_report
  if (!r) return null
  if (r.level === 'NORMAL') return <Pill>Field: normal{r.count != null ? ` (${r.count})` : ''}</Pill>
  return (
    <Pill tone="bad" className="font-bold uppercase">
      {r.level}{r.count != null ? ` · ${r.count} aboard` : ''}
    </Pill>
  )
}

function PoolBlock({ pool }: { pool: Pool }) {
  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="flex items-center gap-2">
          <span className="text-base font-semibold">{pool.class}</span>
          <Pill>{pool.kind === 'RESERVED' ? 'reserved' : 'unreserved'}</Pill>
          <span className="text-sm text-ink-2">{pool.capacity_label}</span>
          <FieldFlag pool={pool} />
        </div>
        <span className="font-mono text-sm text-ink-2" data-testid="formula">{pool.formula}</span>
      </div>
      <div className="mt-1.5 space-y-1.5">
        {mergeRuns(pool.segments).map((r) => (
          <div key={`${r.seg.seg_idx}`} className="grid grid-cols-[minmax(0,11rem)_1fr_4.5rem] items-center gap-3 text-sm">
            <span className="truncate" title={`${r.from} → ${r.to}`}>
              {r.from} → {r.to}{r.count > 1 && <span className="text-ink-2"> · {r.count} segs</span>}
            </span>
            <Bar seg={r.seg} />
            <span className={cn('text-right font-mono font-semibold', r.seg.free <= 0 && 'text-unresolved-ink')}>{barShares(r.seg).used}/{r.seg.cap}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function VehicleCard({ v }: { v: Vehicle }) {
  const names = useVehicleIndex()
  const ended = v.status !== 'SCHEDULED'
  const ends = v.stops.length > 1 ? `${v.stops[0]} → ${v.stops.at(-1)}` : v.stops[0]
  return (
    <div className={cn('rounded-lg border bg-page px-4 py-3', ended && 'opacity-60')} data-testid={`vehicle-${v.vehicle_id}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-lg font-semibold">{nameOf(names, v.vehicle_id)}</span>
        <Pill>{v.mode === 'TRAIN' ? 'Train' : v.mode === 'BUS' ? 'Bus' : v.mode}</Pill>
        {ended && <Pill tone="bad" className="uppercase">{v.status}</Pill>}
        {v.delay_min > 0 && <Pill tone="warn">+{v.delay_min} min</Pill>}
        <span className="ml-auto font-mono text-base">dep {v.depart}</span>
      </div>
      <div className="text-sm text-ink-2">
        <span className="font-mono">{v.vehicle_id}</span> · {ends}{v.stops.length > 2 && ` (${v.stops.length} stops)`}
        {v.boarding_note && <> · {v.boarding_note}</>}
      </div>
      {v.pools.map((p) => <PoolBlock key={p.pool_id} pool={p} />)}
    </div>
  )
}

export function CapacityPanel() {
  const { data, error } = useCapacity('ALLOCATION')
  return (
    <Card
      title="Alternative capacity · per segment"
      aside={
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <Key className="bg-confirmed" label="Confirmed" />
          <Key className="bg-tentative ring-1 ring-inset ring-tentative-ink" label="Tentative" />
          <Key className="bg-boarded" label="Boarded" />
          <Key className="bg-secondary ring-1 ring-line" label="Free" />
        </div>
      }
    >
      <ErrorNote error={error} />
      {!data && !error && <Loading what="capacity" />}
      <div className="max-h-[75vh] space-y-3 overflow-y-auto pr-1">
        {data?.map((v) => <VehicleCard key={v.vehicle_id} v={v} />)}
      </div>
      <p className="mt-3 text-sm text-ink-2">
        Reserved coaches use the exact chart vacancy. Unreserved coaches and buses are filled only up to nominal × buffer. A segment can never go above 100%; the database rejects it.
      </p>
    </Card>
  )
}

function Key({ className, label }: { className: string; label: string }) {
  return <span className="flex items-center gap-1.5"><span className={cn('size-3 rounded-sm', className)} />{label}</span>
}
