import type { Reason, UnresolvedDest } from '@/api/types'
import { Pill } from '@/components/common/StatusChip'
import { Button } from '@/components/ui/button'
import { plural } from '@/lib/format'
import { ALT_LABEL, unresolvedCause } from '@/lib/labels'
import { UNRESOLVED_ANCHOR } from './reviewModel'

const SHOWN = 3

/** The people this plan cannot seat, as something to act on: where they are going, the main reason, and the best fallback. */
export function NoSeatCard({ heads, groups, dests }: { heads: number; groups: number; dests: UnresolvedDest[] | undefined }) {
  if (heads === 0) return null
  const top = [...(dests ?? [])].sort((a, b) => b.heads - a.heads).slice(0, SHOWN)
  const rest = (dests?.length ?? 0) - top.length
  return (
    <div className="rounded-lg border border-unresolved/40 bg-unresolved/5 px-4 py-3" data-testid="no-seat-card">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold uppercase tracking-wide text-unresolved-ink">Needs your attention</div>
          <div className="text-xl font-semibold">
            <span className="font-mono">{heads}</span> {heads === 1 ? 'person has' : 'people have'} no seat yet
            <span className="text-base font-normal text-ink-2"> · {plural(groups, 'group')}</span>
          </div>
        </div>
        <Button variant="outline" size="lg" onClick={() => document.getElementById(UNRESOLVED_ANCHOR)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}>
          See options
        </Button>
      </div>
      <ul className="mt-2 divide-y text-base">
        {top.map((d) => {
          const first = d.items[0]
          const cause = unresolvedCause((first?.reason as (Reason & { primary_cause?: unknown }) | null)?.primary_cause)
          const best = first?.alternatives[0]
          return (
            <li key={d.dest_place} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5">
              <span className="min-w-28 font-semibold">{d.dest_name ?? d.dest_place}</span>
              <span className="font-mono">{d.heads}</span>
              <span>{cause}</span>
              {best && <Pill>Best option: {ALT_LABEL[best.type].toLowerCase()}</Pill>}
            </li>
          )
        })}
        {rest > 0 && <li className="py-1.5 text-ink-2">and {plural(rest, 'more destination')}</li>}
      </ul>
    </div>
  )
}
