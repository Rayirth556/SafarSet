import { useState } from 'react'
import type { SafarEvent } from '@/api/types'
import { Card, ErrorNote, Loading } from '@/components/common/Panels'
import { Switch } from '@/components/ui/switch'
import { useEvents } from '@/hooks/queries'
import { hhmm } from '@/lib/format'
import { cn } from '@/lib/utils'

const s = (v: unknown) => (v == null ? '' : String(v))

/** One plain-language line per event. Unknown types fall back to the type name, so a new event type never breaks the log. */
export function eventSummary(e: SafarEvent): string {
  const p = e.payload
  switch (e.type) {
    case 'SCENARIO_LOADED': return 'Scenario loaded'
    case 'TRAIN_CANCELLED': return `${s(p.vehicle_id)} cancelled`
    case 'TRAIN_DELAYED': return `${s(p.vehicle_id)} delayed ${s(p.delay_min)} min`
    case 'ROAD_CLOSED': return `Road closed: ${s(p.description)}`
    case 'LOAD_REPORT': return `${s(p.vehicle_id)} reported ${s(p.level).toLowerCase()}${p.count != null ? ` (${s(p.count)} aboard)` : ''}`
    case 'VACANCY_UPDATE': return `Chart vacancy set to ${s(p.vacancy)} on ${s(p.pool_id)}`
    case 'NOSHOWS_REPORTED': return `Second-chart vacancies: ${s(p.seats_freed)} seats on ${s(p.vehicle_id)}`
    case 'PASSENGER_BOARDED': return `Group boarded (allocation ${s(p.allocation_id)})`
    case 'PASSENGER_DISPLACED': return `${s(p.group_id)} displaced`
    case 'GROUP_SELF_BOARDED': return `${s(p.group_id)} boarded ${s(p.vehicle_id)} on their own`
    case 'PLAN_PROPOSED': return `Plan proposed${Array.isArray(p.allocations) ? `: ${p.allocations.length} allocations` : ''}`
    case 'BATCH_APPROVED': return `Batch ${s(p.batch_id)} approved`
    case 'SMS_SENT': return `${p.channel === 'PHONE_MOCK' ? 'Message' : s(p.channel)} to ${s(p.group_id)}`
    case 'OPERATOR_OVERRIDE': return `Override on ${s(p.group_id)}: ${s(p.action).toLowerCase().replace('_', ' ')}${p.reason ? ` (${s(p.reason)})` : ''}`
    case 'WEIGHTS_CHANGED': return 'Priority weights changed'
    case 'BUFFER_CHANGED': return `Buffer for ${s(p.mode)} set to ${Math.round(Number(p.buffer_pct) * 100)}%`
    case 'SIM_PARAMS_CHANGED': return 'Demo sliders changed'
    case 'CLOCK_SET': return `Clock set to ${hhmm(Number(p.to_min))}`
    case 'COMMAND_REJECTED': return `Rejected: ${s(p.reason ?? p.error ?? p.message) || 'command refused'}`
    default: return e.type.charAt(0) + e.type.slice(1).toLowerCase().replace(/_/g, ' ')
  }
}

interface Row { key: string; event: SafarEvent; text: string }

/** Consecutive SMS_SENT events collapse into one row; approving a batch would otherwise bury the log in hundreds of lines. */
export function toRows(events: SafarEvent[]): Row[] {
  const rows: Row[] = []
  let run: SafarEvent[] = []
  const flush = () => {
    if (run.length) rows.push({ key: `sms-${run[0].seq}`, event: run[run.length - 1], text: run.length === 1 ? eventSummary(run[0]) : `${run.length} passenger messages sent` })
    run = []
  }
  for (const e of [...events].reverse()) {
    if (e.type === 'SMS_SENT') { run.push(e); continue }
    flush()
    rows.push({ key: String(e.seq), event: e, text: eventSummary(e) })
  }
  flush()
  return rows
}

export function EventLog() {
  const [showRejected, setShowRejected] = useState(false)
  const { data, error } = useEvents(!showRejected)
  const rows = data ? toRows(data.events) : []
  return (
    <Card
      title="Event log"
      aside={
        <label className="flex items-center gap-2 text-base">
          <Switch checked={showRejected} onCheckedChange={setShowRejected} aria-label="Show rejected commands" />
          Show rejected
        </label>
      }
    >
      <ErrorNote error={error} />
      {!data && !error && <Loading what="events" />}
      <div className="max-h-[60vh] divide-y overflow-y-auto pr-1" data-testid="event-log">
        {rows.map((r) => (
          <div key={r.key} className={cn('flex gap-3 py-1.5 text-base', r.event.rejected && 'text-unresolved-ink')}>
            <span className="font-mono text-ink-2">{hhmm(r.event.ts_sim)}</span>
            <span className="w-16 shrink-0 text-sm font-bold uppercase tracking-wide text-navy">{r.event.actor}</span>
            <span>{r.text}</span>
          </div>
        ))}
      </div>
      <p className="mt-3 text-sm text-ink-2">Append-only. Every allocation can be traced back to the event that caused it. Rejected commands are hidden unless you switch them on.</p>
    </Card>
  )
}
