import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as api from '@/api/endpoints'
import { useFieldVehicles, useLoaded, usePassengers } from '@/hooks/queries'
import { useAppState } from '@/hooks/useAppState'
import { STATUS_LABEL, useLive } from '@/live/context'
import { qk } from '@/live/invalidation'
import { pnrTail } from '@/lib/format'
import { nameOf, useVehicleIndex } from '@/lib/vehicles'
import { cn } from '@/lib/utils'
import { JudgeGuideModal } from './JudgeGuideModal'
import { TimelineCard } from '@/routes/sim/SimPage'
import { useActions } from '@/routes/sim/actions'

// Virtual canvas the three screens are laid out on; the whole canvas is scaled to fit the window (projector at 1920x1080 or 1280x720).
const OPERATOR = { w: 1280, h: 1060 }
const FIELD = { w: 390, h: 1060 }
const PHONE = { w: 420, h: 1060 }
const GAP = 24
const CANVAS = { w: OPERATOR.w + FIELD.w + PHONE.w + GAP * 4, h: 1060 + 84 }
const HEADER = 56

/** Largest scale at which the whole canvas fits under the (unscaled) header. */
export const fitScale = (w: number, h: number) => Math.min(w / CANVAS.w, (h - HEADER) / CANVAS.h)

function useFitScale() {
  const [scale, setScale] = useState(() => fitScale(window.innerWidth, window.innerHeight))
  useEffect(() => {
    const on = () => setScale(fitScale(window.innerWidth, window.innerHeight))
    window.addEventListener('resize', on)
    return () => window.removeEventListener('resize', on)
  }, [])
  return scale
}

function Pane({ title, size, src }: { title: string; size: { w: number; h: number }; src: string }) {
  return (
    <div style={{ width: size.w }}>
      <div className="mb-2 text-base font-semibold uppercase tracking-widest text-ink-2">{title}</div>
      <iframe title={title} src={src} style={{ width: size.w, height: size.h }} className="rounded-xl border bg-page shadow-sm" />
    </div>
  )
}

const select = 'h-9 max-w-[22rem] rounded-md border bg-card px-2 text-sm'

/**
 * Operator, field and phone side by side. The field pane starts on the vehicle that the scripted overcrowd report is about; the phone pane starts on
 * the lowest-priority group allocated to that same vehicle (the group the planner moves first when that bus is overcrowded). Both can be changed.
 */
export function DemoPage() {
  const scale = useFitScale()
  const { data: state } = useAppState()
  const { status } = useLive()
  const loaded = useLoaded()
  const names = useVehicleIndex()
  const { data: vehicles } = useFieldVehicles()
  const { data: timeline } = useQuery({ queryKey: [...qk.sim, 'timeline'], queryFn: api.fetchTimeline, enabled: loaded })
  const { data: passengers } = usePassengers({ limit: 500 })
  const act = useActions(state?.loaded ? state.clock : null)

  const scripted = (timeline?.steps.find((s) => s.type === 'LOAD_REPORT')?.payload as { vehicle_id?: string } | undefined)?.vehicle_id
  const [showGuide, setShowGuide] = useState(false)
  const [vehicleId, setVehicleId] = useState<string | null>(null)
  const [phoneKey, setPhoneKey] = useState<string | null>(null)
  const fieldVehicle = vehicleId ?? scripted ?? vehicles?.[0]?.vehicle_id ?? null

  // The lowest-priority group holding a seat on the scripted bus. When that bus is reported overcrowded every group on it loses its seat; the
  // higher-priority ones get the few spare seats on other buses first, so this passenger has no seat until the depot's extra bus arrives, then
  // is moved onto it and told ("moved to ..."). Every displaced group gets a seat once the extra bus is there, so this never ends as "seat lost".
  // If nobody holds a seat there, the highest-ranked group holding one anywhere.
  const candidate = useMemo(() => {
    const held = (passengers?.items ?? []).filter((p) => p.allocation)
    const onBus = held.filter((p) => p.allocation?.vehicle_id === scripted).sort((a, b) => (b.rank ?? 0) - (a.rank ?? 0))
    const pick = onBus[0] ?? held.sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0))[0]
    return pick ? { key: pick.pnr ?? pick.group_id, onBus: onBus.length > 0 } : null
  }, [passengers, scripted])
  // Latched: once chosen the pane keeps following the same passenger while allocations change under it. It re-chooses only if that
  // passenger is not in a newly loaded scenario (the list is complete when it is not paged).
  const [followed, setFollowed] = useState<{ key: string; onBus: boolean } | null>(null)
  const complete = passengers ? passengers.items.length >= passengers.total : false
  const stillThere = followed && passengers ? passengers.items.some((p) => (p.pnr ?? p.group_id) === followed.key) : true
  if (followed === null && candidate) setFollowed(candidate)
  else if (followed && complete && !stillThere) setFollowed(candidate)
  const phone = phoneKey ?? followed?.key ?? null

  return (
    <div className="min-h-screen overflow-hidden bg-page">
      <div className="flex flex-wrap items-center gap-4 border-b-[3px] border-saffron bg-navy px-5 py-2 text-white" style={{ minHeight: HEADER }}>
        <span className="text-lg font-bold">SafarSet</span>
        <span className="text-sm text-white/80">Operator · field · passenger, live</span>

        {state?.loaded && timeline && (
          <div className="mx-auto flex flex-wrap items-center gap-2.5 rounded-lg border border-white/20 bg-white/10 px-3 py-1 font-mono text-xs">
            <span className="font-bold text-saffron uppercase">5-Min Demo:</span>
            <span>Step {Math.min(timeline.next_step + 1, timeline.total)} of {timeline.total}</span>
            <button
              className="rounded bg-saffron px-3 py-1 text-xs font-bold text-navy transition hover:bg-saffron/90 disabled:opacity-40"
              disabled={act.busy || (timeline.next_step >= timeline.total)}
              onClick={() => void act.run('', api.timelineNext)}
              data-testid="header-demo-next"
            >
              {timeline.next_step >= timeline.total ? 'Timeline finished' : `Next ▶ ${timeline.steps[timeline.next_step]?.label ?? ''}`}
            </button>
            <button
              className="rounded border border-white/40 px-2.5 py-1 text-xs text-white transition hover:bg-white/20 disabled:opacity-40"
              disabled={act.busy}
              onClick={() => void act.run('Timeline reset', api.timelineReset)}
              data-testid="header-demo-reset"
            >
              ↺ Reset to 14:00
            </button>
            <button
              className="rounded border border-saffron bg-saffron/15 px-3 py-1 text-xs font-bold text-saffron transition hover:bg-saffron/30"
              onClick={() => setShowGuide(true)}
              data-testid="judge-guide-btn"
            >
              🎓 Judge Guide &amp; Architecture
            </button>
          </div>
        )}

        <span className="ml-auto flex items-center gap-2 text-sm">
          <span className={cn('size-2.5 rounded-full', { ok: 'bg-confirmed', warn: 'bg-tentative', bad: 'bg-unresolved' }[STATUS_LABEL[status].tone])} />{STATUS_LABEL[status].text}
          {state?.loaded && <span className="font-mono font-semibold">SIM {state.clock}</span>}
        </span>
      </div>

      {!state?.loaded ? (
        <p className="p-8 text-lg text-ink-2">No scenario loaded. Open <a className="font-semibold text-navy underline" href="/sim">/sim</a> and load one.</p>
      ) : (
        <div style={{ width: CANVAS.w * scale, height: CANVAS.h * scale }}>
          <div style={{ width: CANVAS.w, transform: `scale(${scale})`, transformOrigin: 'top left' }} className="px-6 pt-3">
            <div className="mb-3 flex flex-wrap items-center gap-4 text-sm" style={{ height: 36 }}>
              <label className="flex items-center gap-2">Field vehicle
                <select className={select} value={fieldVehicle ?? ''} onChange={(e) => setVehicleId(e.target.value)}>
                  {vehicles?.map((v) => <option key={v.vehicle_id} value={v.vehicle_id}>{nameOf(names, v.vehicle_id)} · dep {v.depart}</option>)}
                </select>
              </label>
              <label className="flex items-center gap-2">Passenger phone
                <select className={select} value={phone ?? ''} onChange={(e) => setPhoneKey(e.target.value)}>
                  {!phone && <option value="">Choose…</option>}
                  {passengers?.items.map((p) => (
                    <option key={p.group_id} value={p.pnr ?? p.group_id}>{p.group_id} · {p.pnr ? pnrTail(p.pnr) : 'unreserved'} · to {p.dest_name ?? p.dest_place} · {p.state.toLowerCase()}</option>
                  ))}
                </select>
              </label>
              {!phoneKey && followed && <span className="text-ink-2">{followed.onBus ? `following the lowest-priority group on ${nameOf(names, scripted)}` : 'following the highest-ranked group with a seat'}</span>}
            </div>
            <div className="flex" style={{ gap: GAP }}>
              <Pane title="Operator · control room" size={OPERATOR} src="/operator" />
              <Pane title="Field · conductor / TTE" size={FIELD} src={`/field${fieldVehicle ? `?v=${encodeURIComponent(fieldVehicle)}` : ''}`} />
              <Pane title="Passenger phone" size={PHONE} src={phone ? `/phone/${encodeURIComponent(phone)}?bare` : '/phone?bare'} />
            </div>
          </div>
        </div>
      )}

      {state?.loaded && (
        <details open className="fixed bottom-3 right-3 z-20 w-[430px] rounded-xl border-2 border-dashed border-ink bg-[#ece9df] px-4 py-2 font-mono text-ink shadow-2xl">
          <summary className="cursor-pointer text-sm font-bold uppercase tracking-widest">Demo control (not part of the product)</summary>
          <TimelineCard act={act} compact />
          {act.error && <p role="alert" className="font-mono text-sm text-unresolved-ink">{act.error.message}</p>}
          <p className="font-mono text-sm text-ink-2">{act.log[0]?.text}</p>
        </details>
      )}

      <JudgeGuideModal open={showGuide} onClose={() => setShowGuide(false)} />
    </div>
  )
}
