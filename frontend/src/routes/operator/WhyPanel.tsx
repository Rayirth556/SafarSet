import { useState } from 'react'
import { Card, ErrorNote, Eyebrow, Loading } from '@/components/common/Panels'
import { Pill, StatusChip } from '@/components/common/StatusChip'
import { Button } from '@/components/ui/button'
import { useWhy } from '@/hooks/queries'
import { pnrTail } from '@/lib/format'
import { BLOCKING_WHY, factorLabel, fmtPoints } from '@/lib/labels'
import { nameOf, poolClass, useVehicleIndex } from '@/lib/vehicles'
import { Alternatives } from './Alternatives'
import { OverrideDialog } from './OverrideDialog'

export function WhyPanel({ groupId, onSelect }: { groupId: string | null; onSelect: (id: string) => void }) {
  const { data: why, error, isLoading } = useWhy(groupId)
  const vehicles = useVehicleIndex()
  const [overriding, setOverriding] = useState(false)
  const [history, setHistory] = useState(false)

  if (!groupId) {
    return <Card title="Why"><p className="py-4 text-ink-2">Click a passenger in the table to see the score breakdown and the decision.</p></Card>
  }
  if (error) return <Card title="Why"><ErrorNote error={error} /></Card>
  if (isLoading || !why) return <Card title="Why"><Loading what="decision" /></Card>

  const g = why.group
  const rows = (why.score?.breakdown ?? []).filter(([, pts]) => pts !== 0)
  const alt = why.unresolved?.alternatives ?? []
  const blocking = why.unresolved?.blocking_groups
  const a = why.allocation
  return (
    <Card
      title={<>Why · <span className="font-mono">{g.group_id}</span></>}
      aside={
        <span className="flex flex-wrap items-center justify-end gap-2 text-base text-ink-2">
          {g.pnr ? `PNR ${pnrTail(g.pnr)}` : 'unreserved'} · {g.size === 1 ? '1 person' : `group of ${g.size}`} · to {g.dest_name ?? g.dest_place} <StatusChip state={why.state} />
        </span>
      }
    >
      <div className="grid gap-6 md:grid-cols-2">
        <div>
          <Eyebrow>Priority score</Eyebrow>
          {rows.length === 0 && <p className="py-2 text-ink-2">No priority factors apply.</p>}
          <div className="divide-y">
            {rows.map(([f, pts]) => (
              <div key={f} className="flex justify-between py-1.5 text-base">
                <span>{factorLabel(f)}</span>
                <span className="font-mono font-semibold text-boarded">+{fmtPoints(pts)}</span>
              </div>
            ))}
            {why.score && (
              <div className="flex justify-between py-1.5 text-base font-bold">
                <span>Total</span><span className="font-mono">{fmtPoints(why.score.total)}</span>
              </div>
            )}
          </div>
        </div>
        <div>
          <Eyebrow>Allocation decision</Eyebrow>
          <p className="mt-1 text-base" data-testid="decision-text">{why.decision_text}</p>
          {a && (
            <p className="mt-2 text-base">
              <b>{nameOf(vehicles, a.vehicle_id)}</b> · {poolClass(a.pool_id)} · dep <span className="font-mono">{a.depart}</span> → arr <span className="font-mono">{a.arrive}</span>
              {a.boarding_note && <span className="text-ink-2"> · {a.boarding_note}</span>}
              {a.class_flagged && <Pill tone="warn" className="ml-2">lower class than booked</Pill>}
            </p>
          )}
          {why.rank != null && <p className="mt-1 text-sm text-ink-2">Ranked <span className="font-mono">{why.rank}</span> of <span className="font-mono">{why.of}</span> in this plan.</p>}
          {why.displaced && <p className="mt-2"><Pill tone="bad">displaced: holds the old confirmation until a new batch is approved</Pill></p>}
          {why.held_by_operator && <p className="mt-2"><Pill tone="info">held by operator: {why.held_by_operator.why}</Pill></p>}
          {why.boarded_on_own && <p className="mt-2"><Pill tone="info">boarded {nameOf(vehicles, why.boarded_on_own)} on their own</Pill></p>}
        </div>
      </div>

      {why.state === 'UNRESOLVED' && ((blocking?.length ?? 0) > 0 || alt.length > 0) && (
        <div className="mt-4 rounded-lg border border-unresolved/30 bg-unresolved/5 px-4 py-3">
          {blocking && blocking.length > 0 && (
            <p className="mb-2 text-base" data-testid="blocking">
              <b>Blocked by</b>{' '}
              {blocking.map((id, i) => (
                <span key={id}>{i > 0 && ', '}<button className="font-mono font-semibold text-navy underline" onClick={() => onSelect(id)}>{id}</button></span>
              ))}
              {why.unresolved?.blocking_why && <>: {BLOCKING_WHY[why.unresolved.blocking_why] ?? why.unresolved.blocking_why}.</>}
            </p>
          )}
          {alt.length > 0 && (
            <>
              <Eyebrow className="mb-1">Alternatives · suggestions only, no seats held</Eyebrow>
              <Alternatives items={alt} />
            </>
          )}
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-3">
        <Button variant="outline" size="lg" onClick={() => setOverriding(true)}>Override (reason required)</Button>
        <Button variant="outline" size="lg" onClick={() => setHistory(!history)}>{history ? 'Hide allocation history' : 'Allocation history'}</Button>
      </div>
      {history && (
        <div className="mt-3 divide-y text-base">
          {why.history.length === 0 && <p className="text-ink-2">No allocations yet.</p>}
          {why.history.map((h) => (
            <div key={h.id} className="flex flex-wrap gap-x-4 py-1.5">
              <span className="font-mono text-ink-2">#{h.id}</span>
              <span>{nameOf(vehicles, h.vehicle_id)} · {poolClass(h.pool_id)}</span>
              <Pill>{h.status.toLowerCase()}</Pill>
              {h.batch_id && <span className="font-mono text-ink-2">{h.batch_id}</span>}
            </div>
          ))}
        </div>
      )}
      <OverrideDialog key={g.group_id} why={why} open={overriding} onClose={() => setOverriding(false)} />
    </Card>
  )
}
