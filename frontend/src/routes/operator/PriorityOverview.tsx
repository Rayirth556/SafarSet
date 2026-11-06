import type { PriorityOverview as PriorityOverviewType } from '@/api/types'
import { plural } from '@/lib/format'
import { REPLAY } from '@/api/client'

interface Props {
  overview?: PriorityOverviewType
}

export function PriorityOverview({ overview }: Props) {
  if (!overview) return null

  const { tier_0, tier_1, tier_2, accommodated, unresolved, available_capacity } = overview

  return (
    <div className="rounded-xl border border-line bg-card p-5 shadow-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line pb-3">
        <div>
          <h2 className="text-lg font-bold text-ink">Priority &amp; Recovery Capacity Overview</h2>
          <p className="text-sm text-ink-2">
            Real-time passenger breakdown across 4-layer operational tiers and recovery vehicles
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs font-mono text-ink-2">
          <span className="inline-block size-2 rounded-full bg-confirmed" />
          <span>{REPLAY ? 'Recorded demo (replay)' : 'Live backend SQLite projection'}</span>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {/* Tier 0: Critical */}
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3.5 transition hover:shadow-sm">
          <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-red-700 dark:text-red-300">
            <span className="size-2 rounded-full bg-red-600" />
            Tier 0 · Critical
          </div>
          <div className="mt-1 font-mono text-3xl font-bold text-red-800 dark:text-red-200" data-testid="overview-tier-0">
            {tier_0.heads}
          </div>
          <div className="mt-0.5 text-xs text-red-700/80 dark:text-red-300/80">
            <span className="font-mono font-semibold">{plural(tier_0.groups, 'group')}</span> · Verified emergency
          </div>
        </div>

        {/* Tier 1: High Priority */}
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3.5 transition hover:shadow-sm">
          <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-amber-800 dark:text-amber-300">
            <span className="size-2 rounded-full bg-amber-600" />
            Tier 1 · High
          </div>
          <div className="mt-1 font-mono text-3xl font-bold text-amber-900 dark:text-amber-200" data-testid="overview-tier-1">
            {tier_1.heads}
          </div>
          <div className="mt-0.5 text-xs text-amber-800/80 dark:text-amber-300/80">
            <span className="font-mono font-semibold">{plural(tier_1.groups, 'group')}</span> · Assistance &amp; wait-escalated
          </div>
        </div>

        {/* Tier 2: Standard */}
        <div className="rounded-lg border border-slate-400/30 bg-slate-500/10 p-3.5 transition hover:shadow-sm">
          <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300">
            <span className="size-2 rounded-full bg-slate-500" />
            Tier 2 · Standard
          </div>
          <div className="mt-1 font-mono text-3xl font-bold text-slate-900 dark:text-slate-100" data-testid="overview-tier-2">
            {tier_2.heads}
          </div>
          <div className="mt-0.5 text-xs text-slate-700/80 dark:text-slate-300/80">
            <span className="font-mono font-semibold">{plural(tier_2.groups, 'group')}</span> · Standard travelers
          </div>
        </div>

        {/* Accommodated */}
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3.5 transition hover:shadow-sm">
          <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-300">
            <span className="size-2 rounded-full bg-emerald-600" />
            Accommodated
          </div>
          <div className="mt-1 font-mono text-3xl font-bold text-emerald-800 dark:text-emerald-200" data-testid="overview-accommodated">
            {accommodated.heads}
          </div>
          <div className="mt-0.5 text-xs text-emerald-700/80 dark:text-emerald-300/80">
            <span className="font-mono font-semibold">{plural(accommodated.groups, 'group')}</span> · Allocated / confirmed
          </div>
        </div>

        {/* Unresolved */}
        <div className="rounded-lg border border-unresolved/30 bg-unresolved/10 p-3.5 transition hover:shadow-sm">
          <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-unresolved-ink">
            <span className="size-2 rounded-full bg-unresolved" />
            Unresolved
          </div>
          <div className="mt-1 font-mono text-3xl font-bold text-unresolved-ink" data-testid="overview-unresolved">
            {unresolved.heads}
          </div>
          <div className="mt-0.5 text-xs text-unresolved-ink/80">
            <span className="font-mono font-semibold">{plural(unresolved.groups, 'group')}</span> · Offered alternatives
          </div>
        </div>

        {/* Available Capacity */}
        <div className="rounded-lg border border-blue-500/30 bg-blue-500/10 p-3.5 transition hover:shadow-sm">
          <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-blue-700 dark:text-blue-300">
            <span className="size-2 rounded-full bg-blue-600" />
            Free Capacity
          </div>
          <div className="mt-1 font-mono text-3xl font-bold text-blue-900 dark:text-blue-100" data-testid="overview-capacity">
            {available_capacity}
          </div>
          <div className="mt-0.5 text-xs text-blue-700/80 dark:text-blue-300/80">
            Seats free on relief trains &amp; buses
          </div>
        </div>
      </div>
    </div>
  )
}
