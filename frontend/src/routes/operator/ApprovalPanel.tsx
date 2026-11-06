import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { approveBatch, replan } from '@/api/endpoints'
import type { ApproveResult, BatchItem, DiffCategory } from '@/api/types'
import { ErrorNote, Eyebrow } from '@/components/common/Panels'
import { Pill } from '@/components/common/StatusChip'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useBatchPreview, useCapacity, usePendingBatch, useRules, useUnresolved } from '@/hooks/queries'
import { hhmm, pnrTail, plural } from '@/lib/format'
import { causeLabel, DIFF_HELP, DIFF_LABEL } from '@/lib/labels'
import { nameOf, useVehicleIndex } from '@/lib/vehicles'
import { cn } from '@/lib/utils'
import { ApproveDialog } from './ApproveDialog'
import { NoSeatCard } from './NoSeatCard'
import { consequence, planByVehicle } from './reviewModel'
import { VehicleTable } from './VehicleTable'
import { parseDraft, toDraft, WeightsEditor, type WeightsDraft } from './WeightsEditor'

const LISTED: DiffCategory[] = ['DISPLACED', 'NEWLY_PLACED', 'RESHUFFLED']
const CELLS: DiffCategory[] = ['NEWLY_PLACED', 'DISPLACED', 'RESHUFFLED', 'PLACED', 'UNRESOLVED']
const CELL_TONE: Record<DiffCategory, string> = {
  DISPLACED: 'text-unresolved-ink', NEWLY_PLACED: 'text-confirmed-ink', RESHUFFLED: 'text-tentative-ink', PLACED: 'text-ink-2', UNRESOLVED: 'text-unresolved-ink',
}

export function ApprovalPanel({ onSelect }: { onSelect?: (groupId: string) => void }) {
  const qc = useQueryClient()
  const { data: batch, error } = usePendingBatch()
  const { data: capacity } = useCapacity('ALLOCATION')
  const { data: unresolved } = useUnresolved()
  // the same query the approval dialog opens with, so asking here costs the dialog nothing
  const { data: preview } = useBatchPreview(batch?.batch_id ?? '', undefined, 'en', !!batch && !batch.stale)
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

  const rows = useMemo(() => {
    const departs = new Map(capacity?.map((v) => [v.vehicle_id, v.depart_min]))
    return planByVehicle(batch?.items, (id) => departs.get(id) ?? Number.MAX_SAFE_INTEGER)
  }, [batch?.items, capacity])

  if (error) return <ErrorNote error={error} />
  if (batch === undefined) return null
  if (batch === null) {
    return (
      <div className="rounded-xl border bg-card px-5 py-4 shadow-panel">
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
  const sentence = consequence({ groups: tent.groups, people: tent.heads, messages: preview?.will_send.total ?? null, noSeatPeople: batch.diff.UNRESOLVED.heads,
    kinds: preview?.will_send })
  return (
    <div className="rounded-xl border border-tentative/50 bg-tentative/10" data-testid="approval-panel">
      {/* stays in view while the operator reads down the plan */}
      <div className="sticky top-0 z-20 rounded-t-xl border-b border-tentative/40 bg-card/95 px-5 py-3 shadow-panel backdrop-blur">
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
          <div className="min-w-0 flex-1 basis-[28rem]">
            <Eyebrow className="text-tentative-ink">Awaiting operator approval · no SMS sent yet</Eyebrow>
            <div className="text-xl font-semibold">{batch.batch_id} · {causeLabel(batch.cause)}</div>
            <p className="text-base" data-testid="consequence">{sentence}</p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-3">
            <Button variant="outline" size="lg" onClick={() => setRerunning(true)}>Adjust weights &amp; re-run</Button>
            {batch.stale ? (
              <Button size="lg" onClick={() => replanNow.mutate()} disabled={replanNow.isPending}>Re-plan</Button>
            ) : (
              <Button size="lg" className="font-semibold" onClick={() => setConfirming(true)} data-testid="review-approve">Review &amp; approve</Button>
            )}
          </div>
        </div>
      </div>

      <div className="space-y-4 px-5 py-4">
        <div className="space-y-2">
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

        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          {CELLS.map((c) => (
            <div key={c} className="rounded-lg border bg-card px-3 py-2">
              <div className={cn('text-sm font-semibold uppercase tracking-wide', CELL_TONE[c])}>{DIFF_LABEL[c]}</div>
              <div className="font-mono text-3xl font-semibold leading-tight">{batch.diff[c].heads}</div>
              <div className="text-sm text-ink-2">{plural(batch.diff[c].groups, 'group')} · {DIFF_HELP[c]}</div>
            </div>
          ))}
        </div>

        <section>
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-lg font-semibold">Who goes where <span className="text-base font-normal text-ink-2">· earliest departure first · tap a row for its groups</span></h3>
            <span className="flex items-center gap-3 text-sm text-ink-2">
              <span className="flex items-center gap-1"><span className="inline-block size-3 rounded-sm bg-confirmed" />already confirmed</span>
              <span className="flex items-center gap-1"><span className="inline-block size-3 rounded-sm bg-tentative ring-1 ring-tentative-ink" />offered in this plan</span>
            </span>
          </div>
          <VehicleTable rows={rows} vehicles={capacity} onSelect={onSelect} />
        </section>

        <NoSeatCard heads={batch.diff.UNRESOLVED.heads} groups={batch.diff.UNRESOLVED.groups} dests={unresolved} />

        <details className="rounded-lg border bg-card px-4 py-2" data-testid="audit-list">
          <summary className="cursor-pointer text-base font-semibold">
            Every group in this plan <span className="font-normal text-ink-2">· one by one, for the record</span>
          </summary>
          <div className="mt-2 space-y-2">
            {LISTED.filter((c) => (batch.items?.[c]?.length ?? 0) > 0).map((c) => (
              <details key={c} open={c !== 'NEWLY_PLACED'} className="rounded-lg border px-4 py-2">
                <summary className="cursor-pointer text-base font-semibold">
                  {DIFF_LABEL[c]} <span className="font-mono font-normal text-ink-2">({batch.items![c]!.length} groups)</span>
                </summary>
                <ItemList category={c} items={batch.items![c]!} onSelect={onSelect} />
              </details>
            ))}
          </div>
        </details>
        <ErrorNote error={replanNow.error} />
      </div>

      <ApproveDialog key={batch.batch_id} open={confirming} onClose={() => setConfirming(false)} batchId={batch.batch_id} summary={sentence}
        onApprove={() => approve.mutate(batch.batch_id)} pending={approve.isPending} error={approve.error} />
      <RerunDialog open={rerunning} onClose={() => setRerunning(false)} />
    </div>
  )
}

function Warning({ children }: { children: React.ReactNode }) {
  return <p role="alert" className="rounded-md border border-tentative-ink/40 bg-card px-3 py-2 text-base text-tentative-ink">⚠ {children}</p>
}

function ItemList({ category, items, onSelect }: { category: DiffCategory; items: BatchItem[]; onSelect?: (groupId: string) => void }) {
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
            ? <>now on <b>{nameOf(vehicles, d.vehicle_id as string)}</b>{d.arrive_min != null && <> arriving <span className="font-mono">{hhmm(d.arrive_min as number)}</span></>}</>
            : <span className="text-unresolved-ink">no replacement seat yet</span>
        } else if (category === 'NEWLY_PLACED') {
          what = <>→ <b>{nameOf(vehicles, d.vehicle_id as string)}</b>{d.arrive_min != null && <> arriving <span className="font-mono">{hhmm(d.arrive_min as number)}</span></>}</>
        } else {
          what = <>{d.forced ? 'moved because capacity changed' : 'moved to make room for someone with higher priority'}{typeof d.moved_from === 'string' && <> · from <span className="font-mono">{d.moved_from}</span></>}</>
        }
        return (
          <div key={it.group_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5">
            {onSelect
              ? <button className="font-mono font-semibold text-navy underline" onClick={() => onSelect(it.group_id)} title="Show why this group was placed here">{it.group_id}</button>
              : <span className="font-mono font-semibold">{it.group_id}</span>}
            <span className="text-ink-2">{plural(it.size, 'person', 'people')}{it.pnr ? ` · PNR ${pnrTail(it.pnr)}` : ' · unreserved'} · to {it.dest_name ?? it.dest_place}</span>
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
