import type { Vehicle } from '@/api/types'
import { Pill } from '@/components/common/StatusChip'
import { hhmm, plural, pnrTail } from '@/lib/format'
import { nameOf, useVehicleIndex } from '@/lib/vehicles'
import { barShares } from './CapacityPanel'
import { helpKinds, HELP_LABEL, HELP_ORDER, vehicleFill, type PlanGroup, type VehicleRow } from './reviewModel'

const COLS = 'grid grid-cols-[4rem_minmax(0,1.5fr)_4.5rem_minmax(0,1.1fr)_minmax(0,1.3fr)] items-center gap-x-4'
const CATEGORY_NOTE = { NEWLY_PLACED: 'new seat', RESHUFFLED: 'moved here', DISPLACED: 'replaces lost seat' } as const

function FillBar({ vehicle }: { vehicle: Vehicle | undefined }) {
  if (!vehicle) return <span className="text-ink-2">…</span>
  const f = vehicleFill(vehicle)
  if (f.cap === 0) return <span className="text-ink-2">closed</span>
  const b = barShares({ cap: f.cap, boarded: f.boarded, confirmed: f.confirmed, tentative: f.tentative })
  const label = `${f.used} of ${f.cap} seats at the tightest stretch: ${f.confirmed} confirmed, ${f.tentative} offered in this plan, ${f.boarded} boarded`
  return (
    <div title={label}>
      <div role="img" aria-label={label} className="flex h-3.5 w-full overflow-hidden rounded-sm bg-secondary ring-1 ring-line">
        <div className="h-full bg-boarded" style={{ width: `${b.boarded}%` }} />
        <div className="h-full bg-confirmed" style={{ width: `${b.confirmed}%` }} />
        <div className="h-full bg-tentative ring-1 ring-inset ring-tentative-ink" style={{ width: `${b.tentative}%` }} />
      </div>
      <div className="mt-0.5 font-mono text-sm text-ink-2">{f.used}/{f.cap} seats</div>
    </div>
  )
}

function Group({ g, onSelect }: { g: PlanGroup; onSelect?: (id: string) => void }) {
  const i = g.item
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5 text-base">
      {onSelect
        ? <button className="font-mono font-semibold text-navy underline" onClick={() => onSelect(i.group_id)} title="Show why this group was placed here">{i.group_id}</button>
        : <span className="font-mono font-semibold">{i.group_id}</span>}
      <span className="text-ink-2">{plural(i.size, 'person', 'people')}{i.pnr ? ` · PNR ${pnrTail(i.pnr)}` : ' · unreserved'} · to {i.dest_name ?? i.dest_place}</span>
      {g.arriveMin != null && <span className="font-mono text-ink-2">arrives {hhmm(g.arriveMin)}</span>}
      {helpKinds(i.flags).map((k) => <Pill key={k} tone={k === 'wheelchair' ? 'warn' : 'neutral'}>{HELP_LABEL[k]}</Pill>)}
      <Pill>{CATEGORY_NOTE[g.category as keyof typeof CATEGORY_NOTE]}</Pill>
      {i.detail.operator_override && <Pill tone="info">operator override</Pill>}
    </div>
  )
}

/** The plan seen the way a station master thinks of it: vehicle by vehicle, earliest departure first. A row opens to its groups. */
export function VehicleTable({ rows, vehicles, onSelect }: { rows: VehicleRow[]; vehicles: Vehicle[] | undefined; onSelect?: (id: string) => void }) {
  const names = useVehicleIndex()
  const byId = new Map(vehicles?.map((v) => [v.vehicle_id, v]))
  if (rows.length === 0) return <p className="rounded-lg border bg-card px-4 py-3 text-base text-ink-2">This plan puts nobody on a vehicle.</p>
  return (
    <div className="rounded-lg border bg-card shadow-panel" data-testid="vehicle-table">
      <div className={`${COLS} border-b px-4 py-2 text-sm font-semibold uppercase tracking-wide text-ink-2`}>
        <span>Departs</span><span>Vehicle</span><span className="text-right">People</span>
        <span title="Fullest stretch of the route. Green: already confirmed. Amber: offered in this plan.">Seats</span>
        <span title="Groups that include someone who needs help from staff">Needs staff help (groups)</span>
      </div>
      <div className="divide-y">
        {rows.map((r) => {
          const v = byId.get(r.vehicleId)
          const help = HELP_ORDER.filter((k) => r.help[k] > 0)
          return (
            <details key={r.vehicleId} className="group" data-testid={`vehicle-row-${r.vehicleId}`}>
              <summary className={`${COLS} cursor-pointer px-4 py-3 hover:bg-secondary/40`}>
                <span className="font-mono text-xl font-semibold">{v?.depart ?? '--:--'}</span>
                <span className="min-w-0">
                  <span className="block truncate text-lg font-semibold">{nameOf(names, r.vehicleId)}</span>
                  <span className="block truncate text-sm text-ink-2" title={v?.boarding_note ?? undefined}>
                    to {r.destinations.slice(0, 3).map((d) => `${d.name} ${d.people}`).join(' · ')}{r.destinations.length > 3 ? ` · +${r.destinations.length - 3} more` : ''}
                  </span>
                </span>
                <span className="text-right font-mono text-2xl font-semibold">{r.people}</span>
                <FillBar vehicle={v} />
                <span className="flex flex-wrap gap-1.5">
                  {help.length === 0 ? <span className="text-ink-2">none</span>
                    : help.map((k) => <Pill key={k} tone={k === 'wheelchair' ? 'warn' : 'neutral'}>{HELP_LABEL[k]} {r.help[k]}</Pill>)}
                </span>
              </summary>
              <div className="border-t bg-page/60 px-4 py-2">
                {v?.boarding_note && <p className="pb-1 text-sm text-ink-2">{v.boarding_note}</p>}
                <div className="divide-y">{r.groups.map((g) => <Group key={g.item.group_id} g={g} onSelect={onSelect} />)}</div>
              </div>
            </details>
          )
        })}
      </div>
    </div>
  )
}
