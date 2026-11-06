import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { verifyGroup } from '@/api/endpoints'
import { Card, ErrorNote, Eyebrow, Loading } from '@/components/common/Panels'
import { Pill, StatusChip, TierChip } from '@/components/common/StatusChip'
import { Button } from '@/components/ui/button'
import { useWhy } from '@/hooks/queries'
import { pnrTail } from '@/lib/format'
import { BLOCKING_WHY, factorLabel, fmtPoints } from '@/lib/labels'
import { nameOf, poolClass, useVehicleIndex } from '@/lib/vehicles'
import { Alternatives } from './Alternatives'
import { OverrideDialog } from './OverrideDialog'

export function WhyPanel({ groupId, onSelect }: { groupId: string | null; onSelect: (id: string) => void }) {
  const qc = useQueryClient()
  const { data: why, error, isLoading } = useWhy(groupId)
  const vehicles = useVehicleIndex()
  const [overriding, setOverriding] = useState(false)
  const [history, setHistory] = useState(false)

  const verify = useMutation({
    mutationFn: (type: 'CRITICAL_EMERGENCY' | 'COMPANIONS') =>
      verifyGroup(groupId!, {
        verification_type: type,
        verified: true,
        reason: type === 'CRITICAL_EMERGENCY' ? 'Station master medical officer verified' : 'Station staff confirmed accompanying family',
      }),
    onSettled: () => {
      for (const k of ['passengers', 'why', 'batch', 'kpis', 'state']) {
        void qc.invalidateQueries({ queryKey: [k] })
      }
    },
  })

  if (!groupId) {
    return <Card title="Why"><p className="py-4 text-ink-2">Click a passenger in the table to see the score breakdown and the decision.</p></Card>
  }
  if (error) return <Card title="Why"><ErrorNote error={error} /></Card>
  if (isLoading || !why) return <Card title="Why"><Loading what="decision" /></Card>

  const g = why.group
  const attrs = (g.attrs ?? {}) as Record<string, unknown>
  const rows = (why.score?.breakdown ?? []).filter(([, pts]) => pts !== 0)
  const alt = why.unresolved?.alternatives ?? []
  const blocking = why.unresolved?.blocking_groups
  const a = why.allocation
  const reason = why.reason as Record<string, unknown> | null
  const whyChosen = (reason?.why_chosen ?? {}) as Record<string, unknown>
  const runnerUp = whyChosen.runner_up as { vehicle_id?: string; arrive_min?: number; class_step?: string } | null
  const bindingConstraints = (reason?.binding_constraints ?? []) as { vehicle_id?: string; code?: string; needed?: number; free?: number; segment?: number }[]

  const isVerifiedCritical = Boolean(attrs.medical_emergency || attrs.verified_critical)
  const isCompanionVerified = Boolean(attrs.companion_verified)
  const isLargeGroup = g.size > 4

  return (
    <Card
      title={<>Why · <span className="font-mono">{g.group_id}</span></>}
      aside={
        <span className="flex flex-wrap items-center justify-end gap-2 text-base text-ink-2">
          {g.pnr ? `PNR ${pnrTail(g.pnr)}` : 'unreserved'} · {g.size === 1 ? '1 person' : `group of ${g.size}`} · to {g.dest_name ?? g.dest_place} <StatusChip state={why.state} />
        </span>
      }
    >
      {/* Priority Tier & Verification Header */}
      <div className="mb-4 rounded-lg border bg-secondary/30 p-3.5 space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-ink-2">Assigned Tier:</span>
            <TierChip tier={why.tier ?? 2} name={why.tier_name} />
            {why.escalated && <Pill tone="warn" className="text-xs font-semibold">↑ Escalated from Tier 2</Pill>}
          </div>
          {why.effective_score != null && (
            <div className="text-sm font-mono text-ink-2">
              Effective Priority: <span className="font-bold text-ink">{fmtPoints(why.effective_score)}</span>
            </div>
          )}
        </div>

        {why.tier_reason && (
          <p className="text-sm text-ink-1 font-medium">{why.tier_reason}</p>
        )}

        {why.escalated && why.escalation_reason && (
          <p className="text-xs rounded bg-amber-500/10 border border-amber-500/30 px-2 py-1 text-amber-800 dark:text-amber-300">
            {why.escalation_reason}
          </p>
        )}

        {/* Operator Verification Display */}
        <div className="mt-2 pt-2 border-t border-line/60 flex flex-wrap items-center justify-between gap-2 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-ink-2">Operator Verification:</span>
            {isVerifiedCritical ? (
              <span className="inline-flex items-center gap-1 rounded bg-red-500/15 border border-red-500/30 px-2 py-0.5 text-xs font-bold text-red-700 dark:text-red-300">
                ✓ Verified Medical Emergency (Tier 0)
              </span>
            ) : attrs.medical_need ? (
              <span className="inline-flex items-center gap-1 rounded bg-amber-500/15 border border-amber-500/30 px-2 py-0.5 text-xs font-medium text-amber-800 dark:text-amber-300">
                ⚠ Unverified Medical Need Claim
              </span>
            ) : null}

            {isLargeGroup && (
              isCompanionVerified ? (
                <span className="inline-flex items-center gap-1 rounded bg-blue-500/15 border border-blue-500/30 px-2 py-0.5 text-xs font-bold text-blue-700 dark:text-blue-300">
                  ✓ Verified Companion Group ({g.size} travelers)
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 rounded bg-amber-500/15 border border-amber-500/30 px-2 py-0.5 text-xs font-medium text-amber-800 dark:text-amber-300">
                  ⚠ Unverified Companion Group ({g.size} &gt; 4) · Priority Inheritance Restricted
                </span>
              )
            )}

            {!attrs.medical_need && !isLargeGroup && (
              <span className="text-xs text-ink-2">Standard travel verification</span>
            )}
          </div>

          {/* Quick verification buttons for demonstration */}
          <div className="flex gap-2">
            {!isVerifiedCritical && Boolean(attrs.medical_need) && (
              <Button
                variant="outline"
                size="sm"
                className="h-8 text-xs font-semibold text-red-700 border-red-300 hover:bg-red-50"
                disabled={verify.isPending}
                onClick={() => verify.mutate('CRITICAL_EMERGENCY')}
              >
                {verify.isPending ? 'Verifying…' : 'Verify Critical Case (Tier 0)'}
              </Button>
            )}

            {isLargeGroup && !isCompanionVerified && (
              <Button
                variant="outline"
                size="sm"
                className="h-8 text-xs font-semibold text-blue-700 border-blue-300 hover:bg-blue-50"
                disabled={verify.isPending}
                onClick={() => verify.mutate('COMPANIONS')}
              >
                {verify.isPending ? 'Verifying…' : 'Verify Companions (Promote to Tier 1)'}
              </Button>
            )}
          </div>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Priority Score Breakdown Column */}
        <div>
          <Eyebrow>Mathematical Score Breakdown</Eyebrow>
          {rows.length === 0 && <p className="py-2 text-ink-2">No priority factors apply.</p>}
          <div className="divide-y text-sm">
            {why.factor_scores && (
              <div className="grid grid-cols-4 py-1 text-xs font-semibold text-ink-2 uppercase tracking-wide">
                <span className="col-span-2">Factor</span>
                <span className="text-center">Score / Weight</span>
                <span className="text-right">Points</span>
              </div>
            )}
            {rows.map(([f, pts]) => {
              const scoreVal = why.factor_scores?.[f]
              const weightVal = why.factor_weights?.[f]
              return (
                <div key={f} className="flex justify-between items-center py-1.5">
                  <div className="min-w-0">
                    <div className="font-medium text-ink">{factorLabel(f)}</div>
                    {scoreVal != null && weightVal != null && (
                      <div className="text-xs text-ink-2 font-mono">
                        Score: {scoreVal}/100 × Weight: {weightVal}%
                      </div>
                    )}
                  </div>
                  <span className="font-mono font-semibold text-boarded">+{fmtPoints(pts)}</span>
                </div>
              )
            })}
            {why.base_score != null && (
              <div className="flex justify-between py-1.5 text-sm font-medium text-ink-2">
                <span>Base score subtotal</span>
                <span className="font-mono">{fmtPoints(why.base_score)}</span>
              </div>
            )}
            {why.ageing != null && (
              <div className="flex justify-between py-1.5 text-sm font-medium text-ink-2">
                <span>Waiting-time ageing</span>
                <span className="font-mono text-boarded">+{fmtPoints(why.ageing)}</span>
              </div>
            )}
            {why.score && (
              <div className="flex justify-between py-2 text-base font-bold border-t-2 border-line">
                <span>Final Effective Score</span>
                <span className="font-mono text-lg">{fmtPoints(why.score.total)}</span>
              </div>
            )}
          </div>
        </div>

        {/* Allocation Decision & Vehicle Selection Column */}
        <div>
          <Eyebrow>Allocation Decision &amp; Constraints</Eyebrow>
          <p className="mt-1 text-base font-medium" data-testid="decision-text">{why.decision_text}</p>
          {a && (
            <div className="mt-2.5 rounded-lg border bg-secondary/20 p-2.5 text-base">
              <div>
                <b>{nameOf(vehicles, a.vehicle_id)}</b> · {poolClass(a.pool_id)} · dep <span className="font-mono font-semibold">{a.depart}</span> → arr <span className="font-mono font-semibold">{a.arrive}</span>
              </div>
              {a.boarding_note && <div className="text-sm text-ink-2 mt-0.5">{a.boarding_note}</div>}
              {a.class_flagged && <Pill tone="warn" className="mt-1">lower class than booked</Pill>}
            </div>
          )}

          {runnerUp?.vehicle_id && (
            <p className="mt-2 text-xs text-ink-2">
              Runner-up candidate: <b>{nameOf(vehicles, runnerUp.vehicle_id)}</b> (arrival {runnerUp.arrive_min ? `${Math.floor(runnerUp.arrive_min / 60).toString().padStart(2, '0')}:${(runnerUp.arrive_min % 60).toString().padStart(2, '0')}` : '--:--'}) was evaluated but not chosen.
            </p>
          )}

          {bindingConstraints.length > 0 && (
            <div className="mt-2 text-xs text-ink-2">
              <span className="font-semibold text-ink">Rejected alternatives:</span>{' '}
              {bindingConstraints.map((bc, idx) => (
                <span key={idx}>
                  {idx > 0 && ' · '}
                  {bc.vehicle_id} ({bc.code}: {bc.free ?? 0} free, needed {bc.needed})
                </span>
              ))}
            </div>
          )}

          {why.rank != null && <p className="mt-2 text-sm text-ink-2">Priority rank <span className="font-mono font-bold text-ink">{why.rank}</span> of <span className="font-mono">{why.of}</span> in this plan.</p>}
          {why.displaced && <p className="mt-2"><Pill tone="bad">displaced: holds the old confirmation until a new batch is approved</Pill></p>}
          {why.held_by_operator && <p className="mt-2"><Pill tone="info">held by operator: {why.held_by_operator.why}</Pill></p>}
          {why.boarded_on_own && <p className="mt-2"><Pill tone="info">boarded {nameOf(vehicles, why.boarded_on_own)} on their own</Pill></p>}
        </div>
      </div>

      {/* Unresolved Explanation & Alternatives */}
      {why.state === 'UNRESOLVED' && (
        <div className="mt-4 rounded-lg border border-unresolved/30 bg-unresolved/5 px-4 py-3">
          <div className="mb-2">
            <span className="text-sm font-bold uppercase tracking-wider text-unresolved-ink">Unaccommodated Reason</span>
            <p className="mt-0.5 text-sm text-ink">
              Group size ({g.size}) cannot be split across separate vehicles under hard group-integrity constraints.
              All earlier services reaching {g.dest_name ?? g.dest_place} have exhausted available capacity.
            </p>
          </div>

          {blocking && blocking.length > 0 && (
            <p className="mb-2 text-base" data-testid="blocking">
              <b>Blocked by</b>{' '}
              {blocking.map((id, i) => (
                <span key={id}>{i > 0 && ', '}<button className="font-mono font-semibold text-navy underline" onClick={() => onSelect(id)}>{id}</button></span>
              ))}
              {why.unresolved?.blocking_why && <>: {BLOCKING_WHY[why.unresolved.blocking_why] ?? why.unresolved.blocking_why}.</>}
            </p>
          )}

          {alt.length > 0 && (
            <>
              <Eyebrow className="mb-1">Ranked Alternatives · suggestions only, no seats held</Eyebrow>
              <Alternatives items={alt} />
            </>
          )}
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-3">
        <Button variant="outline" size="lg" onClick={() => setOverriding(true)}>Manual Override (Reason required)</Button>
        <Button variant="outline" size="lg" onClick={() => setHistory(!history)}>{history ? 'Hide allocation history' : 'Allocation history'}</Button>
      </div>

      {history && (
        <div className="mt-3 divide-y text-base">
          {why.history.length === 0 && <p className="text-ink-2">No allocations yet.</p>}
          {why.history.map((h) => (
            <div key={h.id} className="flex flex-wrap gap-x-4 py-1.5">
              <span className="font-mono text-ink-2">#{h.id}</span>
              <span>{nameOf(vehicles, h.vehicle_id)} · {poolClass(h.pool_id)}</span>
              <Pill>{h.status.toLowerCase()}</Pill>
              {h.batch_id && <span className="font-mono text-ink-2">{h.batch_id}</span>}
            </div>
          ))}
        </div>
      )}

      <OverrideDialog key={g.group_id} why={why} open={overriding} onClose={() => setOverriding(false)} />
    </Card>
  )
}
