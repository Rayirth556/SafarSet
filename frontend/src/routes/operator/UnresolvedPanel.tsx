import type { UnresolvedDest } from '@/api/types'
import { Card, ErrorNote, Eyebrow, Loading } from '@/components/common/Panels'
import { useUnresolved } from '@/hooks/queries'
import { plural } from '@/lib/format'
import { BLOCKING_WHY } from '@/lib/labels'
import { Alternatives } from './Alternatives'

function DestCard({ d, onSelect }: { d: UnresolvedDest; onSelect: (id: string) => void }) {
  const top = d.items[0]
  return (
    <div className="rounded-lg border border-unresolved/30 bg-unresolved/5 px-4 py-3" data-testid={`unresolved-${d.dest_place}`}>
      <div className="flex items-baseline justify-between">
        <span className="text-lg font-semibold">{d.dest_name ?? d.dest_place}</span>
        <span className="font-mono text-xl font-semibold text-unresolved-ink">{d.heads}</span>
      </div>
      <div className="text-sm text-ink-2">{plural(d.groups, 'group')} · {plural(d.heads, 'head')}</div>
      {top?.reason?.text && <p className="mt-1 text-base">{top.reason.text}</p>}
      {top && top.alternatives.length > 0 && (
        <div className="mt-2">
          <Eyebrow className="mb-1">Suggestions for {top.group_id} (rank {top.rank}) · hold no seats</Eyebrow>
          <Alternatives items={top.alternatives} />
        </div>
      )}
      <details className="mt-2">
        <summary className="cursor-pointer text-base font-semibold text-navy">All {plural(d.groups, 'group')}</summary>
        <div className="mt-1 divide-y">
          {d.items.map((g) => (
            <div key={g.group_id} className="py-1.5 text-base">
              <button className="font-mono font-semibold text-navy underline" onClick={() => onSelect(g.group_id)}>{g.group_id}</button>
              <span className="text-ink-2"> · {plural(g.size, 'head')} · rank <span className="font-mono">{g.rank}</span>{g.displaced && ' · displaced'}</span>
              {g.blocking_groups && g.blocking_groups.length > 0 && (
                <div className="text-sm text-ink-2">
                  blocked by <span className="font-mono">{g.blocking_groups.join(', ')}</span>
                  {g.blocking_why && <>: {BLOCKING_WHY[g.blocking_why] ?? g.blocking_why}</>}
                </div>
              )}
              {g.alternatives.length > 0 && g !== top && <div className="mt-1"><Alternatives items={g.alternatives} /></div>}
            </div>
          ))}
        </div>
      </details>
    </div>
  )
}

export function UnresolvedPanel({ onSelect }: { onSelect: (id: string) => void }) {
  const { data, error } = useUnresolved()
  const heads = data?.reduce((n, d) => n + d.heads, 0) ?? 0
  return (
    <Card title={<>Unresolved demand · <span className="font-mono">{heads}</span></>}>
      <ErrorNote error={error} />
      {!data && !error && <Loading what="unresolved demand" />}
      {data?.length === 0 && <p className="py-4 text-ink-2">Everyone affected has a seat.</p>}
      <div className="max-h-[60vh] space-y-3 overflow-y-auto pr-1">
        {data?.map((d) => <DestCard key={d.dest_place} d={d} onSelect={onSelect} />)}
      </div>
    </Card>
  )
}
