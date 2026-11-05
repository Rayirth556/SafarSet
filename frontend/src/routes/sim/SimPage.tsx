import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import * as api from '@/api/endpoints'
import type { LoadedState, Timeline, Vehicle } from '@/api/types'
import { ErrorNote } from '@/components/common/Panels'
import { useCapacity, useLoaded } from '@/hooks/queries'
import { useAppState } from '@/hooks/useAppState'
import { qk } from '@/live/invalidation'
import { STATUS_LABEL, useLive } from '@/live/context'
import { nameOf, useVehicleIndex } from '@/lib/vehicles'
import { cn } from '@/lib/utils'
import { useActions, type Act } from './actions'

// Demo controls look deliberately unlike the product: cream paper, dashed frame, monospace. They are NOT part of SafarSet.
const btn = 'w-full rounded-md border border-ink bg-white px-3 py-3 text-left font-mono text-[15px] hover:bg-[#f7f5ee] disabled:opacity-40'
const field = 'rounded-md border border-ink bg-white px-2 py-2 font-mono text-[15px]'

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-5">
      <h2 className="mb-2 font-mono text-[15px] font-bold uppercase tracking-widest">{title}</h2>
      <div className="space-y-2">{children}</div>
    </section>
  )
}

const useTimeline = () => useQuery({ queryKey: [...qk.sim, 'timeline'], queryFn: api.fetchTimeline, enabled: useLoaded() })

// ------------------------------------------------------------------------------------------------ scenario
function ScenarioCard({ act, loaded }: { act: Act; loaded: boolean }) {
  const [seed, setSeed] = useState('42')
  const n = Number(seed)
  const bad = seed.trim() === '' || !Number.isInteger(n)
  return (
    <Section title="Scenario">
      <div className="flex gap-2">
        <label className="flex items-center gap-2 font-mono text-[15px]">seed
          <input className={cn(field, 'w-24')} inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value)} aria-label="seed" />
        </label>
        <button className={cn(btn, 'text-center font-bold')} disabled={bad || act.busy}
          onClick={() => void act.run(loaded ? `Reload scenario (seed ${n})` : `Load scenario (seed ${n})`, () => api.loadScenario({ seed: n }), (r) => `${r.groups} groups, ${r.heads} heads, ${r.vehicles} vehicles`)}>
          {loaded ? 'Reload scenario' : 'Load scenario'}
        </button>
      </div>
      {loaded && <p className="font-mono text-sm text-ink-2">Loading again resets everything, including the timeline.</p>}
    </Section>
  )
}

// ------------------------------------------------------------------------------------------------ disruptions
function Disruptions({ act, state, vehicles, names }: { act: Act; state: LoadedState; vehicles: Vehicle[]; names: ReturnType<typeof useVehicleIndex> }) {
  const trains = vehicles.filter((v) => v.mode === 'TRAIN' && v.status === 'SCHEDULED' && v.vehicle_id !== state.banner.cancelled_vehicle_id)
  const routes = useMemo(() => {
    const m = new Map<string, Vehicle>()
    for (const v of vehicles) if (v.route_id && v.status === 'SCHEDULED' && !m.has(v.route_id)) m.set(v.route_id, v)
    return [...m.values()]
  }, [vehicles])
  const [trainId, setTrainId] = useState('')
  const [minutes, setMinutes] = useState('40')
  const [routeId, setRouteId] = useState('')
  const train = trains.find((t) => t.vehicle_id === trainId) ?? trains[0]
  const road = routes.find((r) => r.route_id === routeId) ?? routes[0]
  const cancelled = state.banner.cancelled_vehicle_id
  const mins = Number(minutes)
  return (
    <Section title="Disruptions">
      <button className={cn(btn, 'border-unresolved-ink bg-unresolved-ink font-bold text-white hover:bg-unresolved-ink/90')} disabled={act.busy || !cancelled}
        onClick={() => void act.run(`Cancel ${nameOf(names, cancelled)}`, () => api.cancelTrain({}), (r) => (r.batch_id ? `plan ${r.batch_id} proposed` : 'done'))}>
        Cancel {nameOf(names, cancelled)} at origin
      </button>
      <div className="flex gap-2">
        <select className={cn(field, 'min-w-0 flex-1')} value={train?.vehicle_id ?? ''} onChange={(e) => setTrainId(e.target.value)} aria-label="train to delay">
          {trains.map((t) => <option key={t.vehicle_id} value={t.vehicle_id}>{nameOf(names, t.vehicle_id)}</option>)}
        </select>
        <input className={cn(field, 'w-16 text-right')} inputMode="numeric" value={minutes} onChange={(e) => setMinutes(e.target.value)} aria-label="delay minutes" />
        <span className="self-center font-mono text-sm">min</span>
      </div>
      <button className={btn} disabled={act.busy || !train || !(mins > 0)}
        onClick={() => void act.run(`Delay ${nameOf(names, train.vehicle_id)} by ${mins} min`, () => api.delayTrain({ vehicle_id: train.vehicle_id, delay_min: mins }), (r) => (r.batch_id ? `plan ${r.batch_id}` : 'done'))}>
        Delay {train ? nameOf(names, train.vehicle_id) : 'a train'} by {Number.isFinite(mins) ? mins : '?'} min
      </button>
      <select className={cn(field, 'w-full')} value={road?.route_id ?? ''} onChange={(e) => setRouteId(e.target.value)} aria-label="road to close">
        {routes.map((r) => <option key={r.route_id!} value={r.route_id!}>{nameOf(names, r.vehicle_id)} · route {r.route_id}</option>)}
      </select>
      <button className={btn} disabled={act.busy || !road}
        onClick={() => void act.run(`Close road: ${nameOf(names, road.vehicle_id)}`, () => api.closeRoad({ route_id: road.route_id!, description: `road closed on route ${road.route_id}` }), (r) => (r.batch_id ? `plan ${r.batch_id}` : 'done'))}>
        Close road: {road ? `${nameOf(names, road.vehicle_id)} (route ${road.route_id})` : 'a route'}
      </button>
    </Section>
  )
}

// ------------------------------------------------------------------------------------------------ simulated field reports
function FieldReports({ act, timeline, names }: { act: Act; timeline: Timeline | undefined; names: ReturnType<typeof useVehicleIndex> }) {
  const over = timeline?.steps.find((s) => s.type === 'LOAD_REPORT')?.payload as { vehicle_id?: string } | undefined
  const chart = timeline?.steps.find((s) => s.type === 'NOSHOWS_REPORTED')?.payload as { vehicle_id?: string; seats_freed?: number } | undefined
  return (
    <Section title="Field reports (simulated)">
      <button className={btn} disabled={act.busy || !over}
        onClick={() => void act.run(`${nameOf(names, over?.vehicle_id)} conductor: overcrowded`, () => api.injectOvercrowd({}), (r) => (r.batch_id ? `re-plan ${r.batch_id} proposed` : 'reported'))}>
        {over ? nameOf(names, over.vehicle_id) : 'Bus'} conductor: overcrowded
      </button>
      <button className={btn} disabled={act.busy || !chart}
        onClick={() => void act.run(`TTE: second-chart vacancies on ${nameOf(names, chart?.vehicle_id)}`, () => api.injectVacancies({}), (r) => (r.batch_id ? `re-plan ${r.batch_id} proposed` : 'reported'))}>
        TTE: {chart?.seats_freed ?? '?'} second-chart vacancies on {chart ? nameOf(names, chart.vehicle_id) : 'a train'}
      </button>
    </Section>
  )
}

// ------------------------------------------------------------------------------------------------ crowd behaviour + departure
function Slider({ label, server, onCommit }: { label: string; server: number; onCommit: (v: number) => Promise<unknown> }) {
  const [draft, setDraft] = useState<number | null>(null)
  const value = draft ?? Math.round(server * 100)
  const commit = async () => {
    if (draft === null) return
    if (draft !== Math.round(server * 100)) await onCommit(draft / 100)
    setDraft(null)
  }
  return (
    <label className="block font-mono text-[15px]">
      <span className="flex justify-between"><span>{label}</span><b>{value}%</b></span>
      <input type="range" min={0} max={100} step={5} value={value} className="mt-1 w-full accent-ink"
        onChange={(e) => setDraft(Number(e.target.value))} onPointerUp={() => void commit()} onKeyUp={() => void commit()} onBlur={() => void commit()} aria-label={label} />
    </label>
  )
}

function Crowd({ act, state, vehicles, names }: { act: Act; state: LoadedState; vehicles: Vehicle[]; names: ReturnType<typeof useVehicleIndex> }) {
  const departable = vehicles.filter((v) => v.status === 'SCHEDULED' && v.role === 'ALLOCATION')
  const [vid, setVid] = useState('')
  const v = departable.find((d) => d.vehicle_id === vid) ?? departable[0]
  const p = state.sim_params
  return (
    <>
      <Section title="Crowd behaviour">
        <Slider label="Compliance with allocation" server={p.compliance_rate} onCommit={(x) => act.run(`Compliance set to ${Math.round(x * 100)}%`, () => api.putSimParams({ compliance_rate: x }))} />
        <Slider label="Walk-on crowd (unregistered)" server={p.walkon_rate} onCommit={(x) => act.run(`Walk-on crowd set to ${Math.round(x * 100)}%`, () => api.putSimParams({ walkon_rate: x }))} />
        <p className="font-mono text-sm text-ink-2">The sliders take effect when a vehicle departs.</p>
        <div className="flex gap-2">
          <select className={cn(field, 'min-w-0 flex-1')} value={v?.vehicle_id ?? ''} onChange={(e) => setVid(e.target.value)} aria-label="vehicle to depart">
            {departable.map((d) => <option key={d.vehicle_id} value={d.vehicle_id}>{nameOf(names, d.vehicle_id)} · dep {d.depart}</option>)}
          </select>
          <button className={cn(btn, 'w-auto text-center')} disabled={act.busy || !v}
            onClick={() => void act.run(`Depart ${nameOf(names, v.vehicle_id)}`, () => api.departVehicle(v.vehicle_id),
              (r) => `${r.boarded_groups.length} boarded, ${r.refused_groups.length} refused, ${r.rusher_groups.length} rushed${r.load_report ? `, load ${String((r.load_report as { level?: string }).level ?? '').toLowerCase()}` : ''}${r.batch_id ? `, re-plan ${r.batch_id}` : ''}`)}>
            Depart
          </button>
        </div>
      </Section>
    </>
  )
}

// ------------------------------------------------------------------------------------------------ clock
function Clock({ act, state }: { act: Act; state: LoadedState }) {
  const [t, setT] = useState('')
  useEffect(() => setT(''), [state.clock_min])
  const value = t || state.clock
  const [h, m] = value.split(':').map(Number)
  const minutes = h * 60 + m
  const valid = /^\d{1,2}:\d{2}$/.test(value) && minutes >= 0 && minutes <= 2880
  return (
    <Section title="Clock">
      <div className="flex items-center gap-2">
        <input type="time" className={cn(field, 'w-32')} value={value} onChange={(e) => setT(e.target.value)} aria-label="clock" />
        <button className={cn(btn, 'w-auto text-center')} disabled={act.busy || !valid} onClick={() => void act.run(`Clock set to ${value}`, () => api.setClock(minutes))}>Set</button>
        <button className={cn(btn, 'w-auto text-center')} disabled={act.busy} onClick={() => void act.run(`Clock +15 min`, () => api.setClock(state.clock_min + 15))}>+15 min</button>
      </div>
      <p className="font-mono text-sm text-ink-2">Now {state.clock}. Moving the clock is logged as an event.</p>
    </Section>
  )
}

// ------------------------------------------------------------------------------------------------ scripted timeline
export function TimelineCard({ act, compact = false }: { act: Act; compact?: boolean }) {
  const { data: tl, error } = useTimeline()
  const { status } = useLive()
  const done = tl ? tl.next_step >= tl.total : false
  const next = tl?.steps[tl.next_step]
  return (
    <Section title="Scripted timeline">
      <ErrorNote error={error} />
      {tl && !compact && (
        <ol className="space-y-1 font-mono text-[15px]">
          {tl.steps.map((s, i) => (
            <li key={s.step} className={cn('flex gap-2 rounded px-2 py-1', i === tl.next_step && 'bg-white font-bold ring-1 ring-ink', i < tl.next_step && 'text-ink-2')}>
              <span className="w-5">{i < tl.next_step ? '✓' : i === tl.next_step ? '▶' : ' '}</span>
              <span className="w-12">{s.at}</span>
              <span className="flex-1">{s.label}</span>
            </li>
          ))}
        </ol>
      )}
      <div className="flex gap-2">
        <button className={cn(btn, 'text-center font-bold')} disabled={act.busy || !tl || done || status === 'reconnecting'} data-testid="timeline-next"
          onClick={() => void act.run('', api.timelineNext, (r) => `Step ${r.played.step}: ${r.played.label}: ${r.result.batch_id ? `plan ${r.result.batch_id}` : r.result.notified_groups != null ? `${r.result.confirmed_groups} confirmed, ${r.result.notified_groups} messaged` : 'done'}`)}>
          {done ? 'Timeline finished' : `Next ▶ ${next?.label ?? ''}`}
        </button>
        <button className={cn(btn, 'w-auto text-center')} disabled={act.busy || !tl} data-testid="timeline-reset"
          onClick={() => void act.run('Timeline reset (scenario reloaded)', api.timelineReset)}>
          Reset
        </button>
      </div>
      {tl && <p className="font-mono text-sm text-ink-2">{tl.label} · step {Math.min(tl.next_step + 1, tl.total)} of {tl.total}</p>}
    </Section>
  )
}

// ------------------------------------------------------------------------------------------------ page
export function SimPage() {
  const { data: state, error } = useAppState()
  const { status } = useLive()
  const act = useActions(state?.loaded ? state.clock : null)
  const { data: timeline } = useTimeline()
  const { data: vehicles } = useCapacity('all')
  const names = useVehicleIndex()
  const loaded = state?.loaded === true

  return (
    <div className="min-h-screen bg-[#ece9df] px-4 py-6 font-mono text-ink">
      <div className="mx-auto max-w-[460px] rounded-xl border-2 border-dashed border-ink px-5 py-5">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="font-mono text-xl font-bold uppercase tracking-widest">Demo controls</h1>
            <p className="font-mono text-[15px]">Drives the simulator. Not part of the product.</p>
          </div>
          <div className="text-right font-mono text-sm">
            <div>{status === 'live' ? '● ' : '○ '}{STATUS_LABEL[status].text}</div>
            {loaded && <div className="font-bold">SIM {state.clock}</div>}
          </div>
        </div>
        <ErrorNote error={error} />
        <ScenarioCard act={act} loaded={loaded} />
        {loaded && vehicles && (
          <>
            <Disruptions act={act} state={state} vehicles={vehicles} names={names} />
            <FieldReports act={act} timeline={timeline} names={names} />
            <Crowd act={act} state={state} vehicles={vehicles} names={names} />
            <Clock act={act} state={state} />
            <TimelineCard act={act} />
          </>
        )}
        <ErrorNote error={act.error} />
        <Section title="Injected events">
          {act.log.length === 0 && <p className="font-mono text-[15px] text-ink-2">Nothing injected yet.</p>}
          <ul className="space-y-1" data-testid="sim-log">
            {act.log.map((e) => (
              <li key={e.id} className={cn('font-mono text-[15px]', !e.ok && 'text-unresolved-ink')}>
                <span className="text-ink-2">{e.at}</span> {e.text}
              </li>
            ))}
          </ul>
        </Section>
        <p className="mt-5 font-mono text-sm text-ink-2">Changes only go through /sim. Names and lists are read from the same API as the other screens.</p>
      </div>
    </div>
  )
}
