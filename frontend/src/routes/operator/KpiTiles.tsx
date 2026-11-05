import type { Heads, Kpis } from '@/api/types'
import { plural } from '@/lib/format'
import { cn } from '@/lib/utils'

function Tile({ label, v, caption, dot, ink }: { label: string; v: Heads; caption: string; dot: string; ink: string }) {
  return (
    <div className="rounded-xl border bg-card px-5 py-4">
      <div className={cn('flex items-center gap-2 text-sm font-semibold uppercase tracking-wide', ink)}>
        <span className={cn('size-2.5 rounded-sm', dot)} />
        {label}
      </div>
      <div className="font-mono text-5xl font-semibold leading-tight" data-testid={`kpi-${label.toLowerCase()}`}>{v.heads}</div>
      <div className="text-base text-ink-2">
        <span className="font-mono">{plural(v.groups, 'group')}</span> · {caption}
      </div>
    </div>
  )
}

export function KpiTiles({ kpis }: { kpis: Kpis }) {
  const extra = [
    kpis.displaced_awaiting_replacement.groups > 0 && `${plural(kpis.displaced_awaiting_replacement.heads, 'person', 'people')} displaced, waiting for a replacement`,
    kpis.held_by_operator.groups > 0 && `${plural(kpis.held_by_operator.heads, 'person', 'people')} held out of automatic planning by the operator`,
  ].filter(Boolean)
  return (
    <div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Tile label="Affected" v={kpis.affected} caption="in the disruption" dot="bg-ink-2" ink="text-ink-2" />
        <Tile label="Tentative" v={kpis.tentative} caption="awaiting approval" dot="bg-tentative" ink="text-tentative-ink" />
        <Tile label="Confirmed" v={kpis.confirmed} caption="SMS sent, frozen" dot="bg-confirmed" ink="text-confirmed-ink" />
        <Tile label="Boarded" v={kpis.boarded} caption="marked by conductor / TTE" dot="bg-boarded" ink="text-boarded" />
        <Tile label="Unresolved" v={kpis.unresolved} caption="offered alternatives" dot="bg-unresolved" ink="text-unresolved-ink" />
      </div>
      {extra.length > 0 && <p className="mt-2 text-base text-tentative-ink">{extra.join(' · ')}</p>}
    </div>
  )
}
