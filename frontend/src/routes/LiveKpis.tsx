import type { Heads } from '@/api/types'
import { AppHeader } from '@/components/common/AppHeader'
import { useAppState } from '@/hooks/useAppState'
import { useLive } from '@/live/context'

function Tile({ label, v, color }: { label: string; v: Heads; color: string }) {
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className={`text-xs font-semibold uppercase tracking-wide ${color}`}>{label}</div>
      <div className="font-mono text-5xl font-semibold">{v.heads}</div>
      <div className="text-sm text-ink-2">{v.groups} groups</div>
    </div>
  )
}

/** F1 bare page: proves the data layer. The real operator dashboard replaces it in F2. */
export function LiveKpis() {
  const { data, error, isLoading } = useAppState()
  const { lastSeq } = useLive()
  return (
    <>
      <AppHeader subtitle="Data layer check" />
      <main className="mx-auto max-w-5xl space-y-4 p-6">
        {isLoading && <p className="text-ink-2">Loading…</p>}
        {error && <p className="text-unresolved-ink">{error.message}</p>}
        {data && !data.loaded && <p className="text-ink-2">No scenario loaded. POST /sim/load-scenario to start.</p>}
        {data?.loaded && (
          <>
            <div className="rounded-xl border bg-card p-4">
              <div className="font-semibold">{data.banner.title}</div>
              <div className="text-sm text-ink-2">
                {data.kpis.composition.pnr_heads} PNR + {data.kpis.composition.ticketed_unreserved_heads} unreserved +
                {' '}~{data.kpis.composition.unreserved_estimate.heads} est. walk-ons
              </div>
            </div>
            <div className="grid grid-cols-5 gap-3">
              <Tile label="Affected" v={data.kpis.affected} color="text-ink-2" />
              <Tile label="Tentative" v={data.kpis.tentative} color="text-tentative-ink" />
              <Tile label="Confirmed" v={data.kpis.confirmed} color="text-confirmed-ink" />
              <Tile label="Boarded" v={data.kpis.boarded} color="text-boarded" />
              <Tile label="Unresolved" v={data.kpis.unresolved} color="text-unresolved-ink" />
            </div>
            <p className="font-mono text-sm text-ink-2">last_seq {lastSeq} · clock {data.clock}</p>
          </>
        )}
      </main>
    </>
  )
}
