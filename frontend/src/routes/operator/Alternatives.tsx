import type { Alternative } from '@/api/types'
import { hhmm } from '@/lib/format'
import { ALT_LABEL } from '@/lib/labels'
import { nameOf, titleCase, useVehicleIndex } from '@/lib/vehicles'

interface Leg { from?: string; to?: string; depart_min?: number; arrive_min?: number; vehicle_id?: string }

/** Ranked alternatives for a group that could not be placed. They are suggestions: none of them holds a seat. */
export function Alternatives({ items }: { items: Alternative[] }) {
  const vehicles = useVehicleIndex()
  if (!items.length) return null
  return (
    <ol className="space-y-1.5 text-base">
      {[...items].sort((a, b) => a.rank - b.rank).map((a) => {
        const legs = Array.isArray(a.legs) ? (a.legs as Leg[]) : []
        return (
          <li key={`${a.type}-${a.rank}`} className="flex gap-2">
            <span className="font-mono font-semibold text-navy">{a.rank}</span>
            <span>
              <b>{ALT_LABEL[a.type] ?? a.type}</b>
              {legs.length > 0 && (
                <>
                  {': '}
                  {legs.map((l, i) => (
                    <span key={i}>
                      {i > 0 && ', then '}
                      {titleCase(l.from ?? '?')} → {titleCase(l.to ?? '?')} by {nameOf(vehicles, l.vehicle_id)}
                      {l.depart_min != null && <span className="font-mono"> ({hhmm(l.depart_min)}–{hhmm(l.arrive_min)})</span>}
                    </span>
                  ))}
                </>
              )}
              {legs.length === 0 && typeof a.arrive_min === 'number' && <span className="font-mono"> arrives {hhmm(a.arrive_min)}</span>}
              {a.type === 'WAITLIST' && typeof a.position === 'number' && <span className="font-mono"> · position {a.position}</span>}
              {a.note && <span className="text-ink-2"> — {a.note}</span>}
            </span>
          </li>
        )
      })}
    </ol>
  )
}
