import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { overrideGroup } from '@/api/endpoints'
import type { OverrideAction, OverrideBody, Why } from '@/api/types'
import { ErrorNote } from '@/components/common/Panels'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { useCapacity } from '@/hooks/queries'
import { vehicleName } from '@/lib/vehicles'

const ACTIONS: { value: OverrideAction; label: string; help: string }[] = [
  { value: 'ASSIGN', label: 'Assign to a vehicle', help: 'Put this group on a chosen vehicle and journey.' },
  { value: 'UNASSIGN', label: 'Take off their seat', help: 'Remove the seat and hold the group out of automatic planning.' },
  { value: 'RESUME_AUTO', label: 'Resume automatic planning', help: 'Return a held group to the planner.' },
]
const select = 'h-10 w-full rounded-lg border bg-card px-3 text-base'

/** Operator override. The reason is mandatory and is logged with the event. */
export function OverrideDialog({ why, open, onClose }: { why: Why; open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const { data: vehicles } = useCapacity('ALLOCATION')
  const [action, setAction] = useState<OverrideAction>('ASSIGN')
  const [reason, setReason] = useState('')
  const [vehicleId, setVehicleId] = useState('')
  const [poolId, setPoolId] = useState('')
  const [board, setBoard] = useState('0')
  const [alight, setAlight] = useState('')

  const usable = (vehicles ?? []).filter((v) => v.status === 'SCHEDULED')
  const vehicle = usable.find((v) => v.vehicle_id === vehicleId)
  const pool = vehicle?.pools.find((p) => p.pool_id === poolId)

  const mut = useMutation({
    mutationFn: (body: OverrideBody) => overrideGroup(why.group.group_id, body),
    onSuccess: () => { setReason(''); onClose() },
    onSettled: () => { for (const k of ['batch', 'passengers', 'why', 'capacity', 'unresolved', 'state']) void qc.invalidateQueries({ queryKey: [k] }) },
  })

  const needsSeat = action === 'ASSIGN'
  const missing = !reason.trim() ? 'A reason is required.' : needsSeat && (!vehicle || !pool || alight === '') ? 'Choose a vehicle, a pool and the stops.' : null
  const submit = () => {
    if (missing) return
    mut.mutate(needsSeat
      ? { action, reason: reason.trim(), pool_id: poolId, board_idx: Number(board), alight_idx: Number(alight) }
      : { action, reason: reason.trim() })
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl text-base">
        <DialogHeader>
          <DialogTitle className="text-xl">Override · <span className="font-mono">{why.group.group_id}</span></DialogTitle>
          <DialogDescription className="text-base">
            {why.group.size === 1 ? '1 person' : `Group of ${why.group.size}`} to {why.group.dest_name ?? why.group.dest_place}. A reason is mandatory and is written to the event log. Overrides produce a new plan to approve.
          </DialogDescription>
        </DialogHeader>

        <label className="block">
          <span className="mb-1 block font-medium">Action</span>
          <select className={select} value={action} onChange={(e) => setAction(e.target.value as OverrideAction)}>
            {ACTIONS.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
          </select>
          <span className="text-sm text-ink-2">{ACTIONS.find((a) => a.value === action)!.help}</span>
        </label>

        {needsSeat && (
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block sm:col-span-2">
              <span className="mb-1 block font-medium">Vehicle</span>
              <select className={select} value={vehicleId} onChange={(e) => { setVehicleId(e.target.value); setPoolId(''); setBoard('0'); setAlight('') }}>
                <option value="">Choose…</option>
                {usable.map((v) => <option key={v.vehicle_id} value={v.vehicle_id}>{vehicleName(v)} · {v.vehicle_id} · dep {v.depart}</option>)}
              </select>
            </label>
            <label className="block sm:col-span-2">
              <span className="mb-1 block font-medium">Coach / pool</span>
              <select className={select} value={poolId} onChange={(e) => setPoolId(e.target.value)} disabled={!vehicle}>
                <option value="">Choose…</option>
                {vehicle?.pools.map((p) => <option key={p.pool_id} value={p.pool_id}>{p.class} · {p.kind.toLowerCase()} · {p.capacity_label}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block font-medium">Board at</span>
              <select className={select} value={board} onChange={(e) => setBoard(e.target.value)} disabled={!vehicle}>
                {vehicle?.stops.slice(0, -1).map((s, i) => <option key={i} value={i}>{s}</option>)}
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block font-medium">Get off at</span>
              <select className={select} value={alight} onChange={(e) => setAlight(e.target.value)} disabled={!vehicle}>
                <option value="">Choose…</option>
                {vehicle?.stops.map((s, i) => (i > Number(board) ? <option key={i} value={i}>{s}</option> : null))}
              </select>
            </label>
          </div>
        )}

        <label className="block">
          <span className="mb-1 block font-medium">Reason (required)</span>
          <Textarea className="min-h-20 text-base" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why is the control room overriding the planner?" />
        </label>

        <ErrorNote error={mut.error} />
        <DialogFooter>
          <Button variant="outline" size="lg" onClick={onClose}>Cancel</Button>
          <Button size="lg" className="font-semibold" disabled={!!missing || mut.isPending} onClick={submit} title={missing ?? undefined}>
            {mut.isPending ? 'Applying…' : 'Apply override'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
