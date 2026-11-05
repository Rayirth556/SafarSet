import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { approveBatch, replan } from '@/api/endpoints'
import type { ApproveResult, BatchItem, DiffCategory } from '@/api/types'
import { ErrorNote, Eyebrow } from '@/components/common/Panels'
import { Pill } from '@/components/common/StatusChip'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { usePendingBatch, useRules } from '@/hooks/queries'
import { hhmm, pnrTail, plural } from '@/lib/format'
import { causeLabel, DIFF_HELP, DIFF_LABEL } from '@/lib/labels'
import { nameOf, useVehicleIndex } from '@/lib/vehicles'
import { cn } from '@/lib/utils'
import { parseDraft, toDraft, WeightsEditor, type WeightsDraft } from './WeightsEditor'

const LISTED: DiffCategory[] = ['DISPLACED', 'NEWLY_PLACED', 'RESHUFFLED']
const CELLS: DiffCategory[] = ['DISPLACED', 'NEWLY_PLACED', 'RESHUFFLED', 'PLACED', 'UNRESOLVED']
const CELL_TONE: Record<DiffCategory, string> = {
  DISPLACED: 'text-unresolved-ink', NEWLY_PLACED: 'text-confirmed-ink', RESHUFFLED: 'text-tentative-ink', PLACED: 'text-ink-2', UNRESOLVED: 'text-unresolved-ink',
}

export function ApprovalPanel() {
  const qc = useQueryClient()
  const { data: batch, error } = usePendingBatch()
  const [confirming, setConfirming] = useState(false)
  const [rerunning, setRerunning] = useState(false)
  const [done, setDone] = useState<ApproveResult | null>(null)

  const approve = useMutation({
    mutationFn: (id: string) => approveBatch(id),
    onSuccess: (r) => { setDone(r); setConfirming(false) },
    onSettled: () => void qc.invalidateQueries({ queryKey: ['batch'] }),
  })
  const replanNow = useMutation({
    mutationFn: () => replan({}),
    onSuccess: () => setDone(null),
    onSettled: () => void qc.invalidateQueries({ queryKey: ['batch'] }),
  })

  if (error) return <ErrorNote error={error} />
  if (batch === undefined) return null
  if (batch === null) {
    return (
      <div className="rounded-xl border bg-card px-5 py-4">
        <Eyebrow>Approval</Eyebrow>
        <div className="text-lg font-semibold">No plan is awaiting approval</div>
        {done && (
          <p className="text-confirmed-ink" role="status">
            Approved {done.batch_id}: {plural(done.confirmed_groups, 'group')} confirmed, {plural(done.notified_groups, 'group')} messaged.
          </p>
        )}
        <ErrorNote error={replanNow.error} />
      </div>
    )
  }

  const stillHeld = (batch.items?.DISPLACED ?? []).filter((i) => i.detail.old_sms_still_held).length
  const tent = batch.allocations.tentative
  return (
    <div className="rounded-xl border border-tentative/50 bg-tentative/10 px-5 py-4" data-testid="approval-panel">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <Eyebrow className="text-tentative-ink">Awaiting operator approval · no SMS sent yet</Eyebrow>
          <div className="text-xl font-semibold">
            {batch.batch_id} · {causeLabel(batch.cause)}
          </div>
          <div className="text-base">
            <span className="font-mono">{tent.heads}</span> heads tentative in <span className="font-mono">{plural(tent.groups, 'group')}</span> ·{' '}
            <span className="font-mono">{batch.diff.UNRESOLVED.heads}</span> unresolved with alternatives
          </div>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button variant="outline" size="lg" onClick={() => setRerunning(true)}>Adjust weights &amp; re-run</Button>
          {batch.stale ? (
            <Button size="lg" onClick={() => replanNow.mutate()} disabled={replanNow.isPending}>Re-plan</Button>
          ) : (
            <Button size="lg" className="font-semibold" onClick={() => setConfirming(true)} data-testid="review-approve">Review &amp; approve batch</Button>
          )}
        </div>
      </div>

      <div className="mt-3 space-y-2">
        {batch.stale && (
          <Warning>Capacity this plan relies on has changed, so it can no longer be approved. Re-plan to get a current proposal.</Warning>
        )}
        {batch.weights_out_of_date && (
          <Warning>The priority weights were edited after this plan was made. This plan still uses the old weights: use “Adjust weights &amp; re-run” to apply them.</Warning>
        )}
        {stillHeld > 0 && (
          <Warning>
            {plural(stillHeld, 'displaced group')} still hold{stillHeld === 1 ? 's' : ''} the old SMS confirmation until this batch is approved.
          </Warning>
        )}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        {CELLS.map((c) => (
          <div key={c} className="rounded-lg border bg-card px-3 py-2">
            <div className={cn('text-sm font-semibold uppercase tracking-wide', CELL_TONE[c])}>{DIFF_LABEL[c]}</div>
            <div className="font-mono text-3xl font-semibold leading-tight">{batch.diff[c].heads}</div>
            <div className="text-sm text-ink-2">{plural(batch.diff[c].groups, 'group')} · {DIFF_HELP[c]}</div>
          </div>
        ))}
      </div>

      <div className="mt-3 space-y-2">
        {LISTED.filter((c) => (batch.items?.[c]?.length ?? 0) > 0).map((c) => (
          <details key={c} open={c !== 'NEWLY_PLACED'} className="rounded-lg border bg-card px-4 py-2">
            <summary className="cursor-pointer text-base font-semibold">
              {DIFF_LABEL[c]} <span className="font-mono font-normal text-ink-2">({batch.items![c]!.length} groups)</span>
            </summary>
            <ItemList category={c} items={batch.items![c]!} />
          </details>
        ))}
      </div>
      <ErrorNote error={replanNow.error} />

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent className="sm:max-w-lg text-base">
          <DialogHeader>
            <DialogTitle className="text-xl">Approve {batch.batch_id}?</DialogTitle>
            <DialogDescription className="text-base">
              This confirms {plural(tent.groups, 'tentative group')} ({plural(tent.heads, 'head')}), freezes them, and sends the passenger messages. It cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <ErrorNote error={approve.error} />
          {approve.error && (approve.error as { kind?: string }).kind === 'StaleBatch' && (
            <p className="text-base">The plan is out of date. Close this and re-plan.</p>
          )}
          <DialogFooter>
            <Button variant="outline" size="lg" onClick={() => setConfirming(false)}>Cancel</Button>
            <Button size="lg" className="font-semibold" onClick={() => approve.mutate(batch.batch_id)} disabled={approve.isPending} data-testid="confirm-approve">
              {approve.isPending ? 'Approving…' : 'Approve and send messages'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <RerunDialog open={rerunning} onClose={() => setRerunning(false)} />
    </div>
  )
}

function Warning({ children }: { children: React.ReactNode }) {
  return <p role="alert" className="rounded-md border border-tentative-ink/40 bg-card px-3 py-2 text-base text-tentative-ink">⚠ {children}</p>
}

function ItemList({ category, items }: { category: DiffCategory; items: BatchItem[] }) {
  const [all, setAll] = useState(false)
  const vehicles = useVehicleIndex()
  const shown = all ? items : items.slice(0, 8)
  return (
    <div className="mt-2 divide-y text-base">
      {shown.map((it) => {
        const d = it.detail
        let what: React.ReactNode = null
        if (category === 'DISPLACED') {
          what = d.replaced
            ? <>moved to <b>{nameOf(vehicles, d.vehicle_id as string)}</b>{d.arrive_min != null && <> arriving <span className="font-mono">{hhmm(d.arrive_min as number)}</span></>}</>
            : <span className="text-unresolved-ink">no replacement yet</span>
        } else if (category === 'NEWLY_PLACED') {
          what = <>→ <b>{nameOf(vehicles, d.vehicle_id as string)}</b>{d.arrive_min != null && <> arriving <span className="font-mono">{hhmm(d.arrive_min as number)}</span></>}</>
        } else {
          what = <>{d.forced ? 'forced by a capacity change' : 'chosen by the bounded reshuffle'}{typeof d.moved_from === 'string' && <> · from <span className="font-mono">{d.moved_from}</span></>}</>
        }
        return (
          <div key={it.group_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5">
            <span className="font-mono font-semibold">{it.group_id}</span>
            <span className="text-ink-2">{plural(it.size, 'head')}{it.pnr ? ` · PNR ${pnrTail(it.pnr)}` : ' · unreserved'} · to {it.dest_name ?? it.dest_place}</span>
            <span>{what}</span>
            {category === 'DISPLACED' && typeof d.cause === 'string' && <Pill>{d.cause.replace(/_/g, ' ').toLowerCase()}</Pill>}
            {d.old_sms_still_held && <Pill tone="warn">still holds old SMS</Pill>}
            {d.operator_override && <Pill tone="info">operator override</Pill>}
          </div>
        )
      })}
      {items.length > 8 && (
        <button className="py-2 text-base font-semibold text-navy underline" onClick={() => setAll(!all)}>
          {all ? 'Show fewer' : `Show all ${items.length}`}
        </button>
      )}
    </div>
  )
}

function RerunDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const { data: rules } = useRules()
  const [draft, setDraft] = useState<WeightsDraft | null>(null)
  const [localError, setLocalError] = useState<string | null>(null)
  const value = draft ?? (rules ? toDraft(rules.weights) : {})

  const rerun = useMutation({
    mutationFn: (weights: Record<string, number>) => replan({ weights }),
    onSuccess: () => { setDraft(null); onClose() },
    onSettled: () => { void qc.invalidateQueries({ queryKey: ['batch'] }); void qc.invalidateQueries({ queryKey: ['rules'] }) },
  })
  const submit = () => {
    const parsed = parseDraft(value)
    if ('error' in parsed) return setLocalError(parsed.error)
    setLocalError(null)
    rerun.mutate(parsed.weights)
  }
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) { setDraft(null); setLocalError(null); onClose() } }}>
      <DialogContent className="sm:max-w-lg text-base">
        <DialogHeader>
          <DialogTitle className="text-xl">Adjust weights &amp; re-run</DialogTitle>
          <DialogDescription className="text-base">
            Plans everyone from scratch with these priority weights. A new batch is proposed; nothing is sent until you approve it.
          </DialogDescription>
        </DialogHeader>
        <WeightsEditor value={value} onChange={setDraft} />
        {localError && <p role="alert" className="text-base text-unresolved-ink">{localError}</p>}
        <ErrorNote error={rerun.error} />
        <DialogFooter>
          <Button variant="outline" size="lg" onClick={onClose}>Cancel</Button>
          <Button size="lg" className="font-semibold" onClick={submit} disabled={rerun.isPending || !rules}>{rerun.isPending ? 'Re-running…' : 'Re-run with these weights'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

