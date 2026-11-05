import type { BannerItem, LoadedState } from '@/api/types'
import { cn } from '@/lib/utils'

const KIND: Record<BannerItem['kind'], string> = { TRAIN_CANCELLED: 'CANCELLED', TRAIN_DELAYED: 'DELAYED', ROAD_CLOSED: 'ROAD CLOSED' }

export function DisruptionBanner({ state }: { state: LoadedState }) {
  const { banner, kpis } = state
  if (!banner.active) {
    return (
      <div className="rounded-xl border bg-card px-5 py-4">
        <div className="text-lg font-semibold">No disruption</div>
        <div className="text-ink-2">Waiting for a disruption. Everything shown here is SIMULATED.</div>
      </div>
    )
  }
  const c = kpis.composition
  return (
    <div className="rounded-xl border border-unresolved/30 bg-unresolved/10 px-5 py-4">
      <ul className="space-y-1.5">
        {banner.items.map((it) => (
          <li key={it.seq} className="flex items-center gap-3">
            <span className={cn('rounded px-2 py-0.5 text-sm font-bold tracking-wide text-white', it.kind === 'TRAIN_CANCELLED' ? 'bg-unresolved-ink' : 'bg-tentative-ink')}>
              {KIND[it.kind]}
            </span>
            <span className="text-lg font-semibold">{it.text}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-base">
        <span className="font-mono font-semibold">{c.pnr_heads}</span> PNR + <span className="font-mono font-semibold">{c.ticketed_unreserved_heads}</span> unreserved +{' '}
        <span className="font-mono font-semibold">~{c.unreserved_estimate.heads}</span> est. walk-ons
        <span className="text-ink-2"> (walk-ons are an estimate and are not counted as affected)</span>
      </p>
    </div>
  )
}
