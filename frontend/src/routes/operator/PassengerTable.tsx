import { useEffect, useState } from 'react'
import type { Passenger } from '@/api/types'
import { Card, ErrorNote, Loading } from '@/components/common/Panels'
import { Pill, StatusChip } from '@/components/common/StatusChip'
import { Input } from '@/components/ui/input'
import { usePassengers } from '@/hooks/queries'
import { fmtPoints } from '@/lib/labels'
import { pnrTail } from '@/lib/format'
import { nameOf, poolClass, useVehicleIndex } from '@/lib/vehicles'
import { cn } from '@/lib/utils'

const PAGE = 10
const STATUSES = ['', 'UNRESOLVED', 'TENTATIVE', 'CONFIRMED', 'BOARDED']

function useDebounced<T>(value: T, ms = 250) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

function Flags({ p }: { p: Passenger }) {
  const f = p.flags
  const chips = [
    f.senior && 'senior', f.disability && 'medical / disability', f.wheelchair && 'wheelchair', f.child && 'child', f.pregnant && 'pregnant',
    f.deadline && `deadline ${f.deadline}`,
  ].filter(Boolean) as string[]
  return (
    <>
      {chips.map((c) => <Pill key={c} className="mr-1">{c}</Pill>)}
      {p.displaced && <Pill tone="bad" className="mr-1">displaced</Pill>}
      {p.held_by_operator && <Pill tone="info" className="mr-1">held by operator</Pill>}
    </>
  )
}

export function PassengerTable({ selected, onSelect }: { selected: string | null; onSelect: (id: string) => void }) {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [dest, setDest] = useState<{ place: string; name: string } | null>(null)
  const q = useDebounced(search.trim())
  // the page belongs to the filters it was chosen under: changing a filter silently returns to page 1
  const filterKey = `${q}|${status}|${dest?.place ?? ''}`
  const [paged, setPaged] = useState({ key: filterKey, n: 0 })
  const page = paged.key === filterKey ? paged.n : 0
  const setPage = (n: number) => setPaged({ key: filterKey, n })
  const vehicles = useVehicleIndex()
  const { data, error, isLoading } = usePassengers({ status: status || undefined, dest: dest?.place, q: q || undefined, limit: PAGE, offset: page * PAGE })

  const total = data?.total ?? 0
  const from = total === 0 ? 0 : page * PAGE + 1
  const to = Math.min(total, (page + 1) * PAGE)

  return (
    <Card title="Affected passengers">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <Input className="h-10 w-56 text-base" placeholder="Group ID or PNR" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search by group ID or PNR" />
        <select className="h-10 rounded-lg border bg-card px-3 text-base" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
          {STATUSES.map((s) => <option key={s} value={s}>{s ? s.charAt(0) + s.slice(1).toLowerCase() : 'All statuses'}</option>)}
        </select>
        {dest && (
          <button className="flex items-center gap-2 rounded-lg bg-navy px-3 py-1.5 text-base text-white" onClick={() => setDest(null)}>
            To {dest.name} <span aria-hidden>✕</span><span className="sr-only">clear destination filter</span>
          </button>
        )}
      </div>
      <ErrorNote error={error} />
      {isLoading && <Loading what="passengers" />}
      {data && data.items.length === 0 && <p className="py-6 text-center text-ink-2">No passengers match these filters.</p>}
      {data && data.items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-base">
            <thead>
              <tr className="border-b text-sm text-ink-2">
                <th className="py-2 pr-3 font-medium">Passenger</th>
                <th className="pr-3 font-medium">To</th>
                <th className="pr-3 text-right font-medium">Score</th>
                <th className="pr-3 font-medium">Status</th>
                <th className="font-medium">Assigned to</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((p) => {
                const a = p.allocation
                return (
                  <tr
                    key={p.group_id}
                    tabIndex={0}
                    aria-selected={selected === p.group_id}
                    onClick={() => onSelect(p.group_id)}
                    onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onSelect(p.group_id))}
                    className={cn('cursor-pointer border-b align-top hover:bg-page focus-visible:outline-2 focus-visible:outline-navy', selected === p.group_id && 'bg-boarded/10')}
                    data-testid={`row-${p.group_id}`}
                  >
                    <td className="py-2 pr-3">
                      <div className="font-semibold">
                        <span className="font-mono">{p.group_id}</span>
                        <span className="font-normal text-ink-2"> · {p.size === 1 ? '1 person' : `group of ${p.size}`}</span>
                      </div>
                      <div className="font-mono text-sm text-ink-2">{p.pnr ? `PNR ${pnrTail(p.pnr)}` : 'UTS ticket · unreserved'} · {p.class}</div>
                      <div className="mt-0.5"><Flags p={p} /></div>
                    </td>
                    <td className="pr-3">
                      <button
                        className="text-left underline decoration-dotted underline-offset-2 hover:text-navy"
                        title="Filter by this destination"
                        onClick={(e) => { e.stopPropagation(); setDest({ place: p.dest_place, name: p.dest_name ?? p.dest_place }) }}
                      >
                        {p.dest_name ?? p.dest_place}
                      </button>
                    </td>
                    <td className="pr-3 text-right font-mono font-semibold">{p.score == null ? '—' : fmtPoints(p.score)}</td>
                    <td className="pr-3"><StatusChip state={p.state} /></td>
                    <td>
                      {a ? (
                        <>
                          <div>{nameOf(vehicles, a.vehicle_id)} · {poolClass(a.pool_id)}</div>
                          <div className="font-mono text-sm text-ink-2">{a.vehicle_id} · dep {a.depart ?? '--:--'}</div>
                        </>
                      ) : p.boarded_on_own ? (
                        <span className="text-boarded">boarded {nameOf(vehicles, p.boarded_on_own)} on their own</span>
                      ) : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-3 flex items-center justify-between text-base text-ink-2">
        <span>Showing <span className="font-mono">{from}–{to}</span> of <span className="font-mono">{total}</span> · click a row to see why</span>
        <span className="flex gap-2">
          <PageButton disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</PageButton>
          <PageButton disabled={to >= total} onClick={() => setPage(page + 1)}>Next</PageButton>
        </span>
      </div>
    </Card>
  )
}

function PageButton({ children, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button {...p} className="rounded-lg border bg-card px-3 py-1.5 text-base font-medium text-ink hover:bg-page disabled:opacity-40">{children}</button>
}
