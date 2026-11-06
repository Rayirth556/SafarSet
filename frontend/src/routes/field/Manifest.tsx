import { useMutation, useQueryClient } from '@tanstack/react-query'
import { boardGroup } from '@/api/endpoints'
import type { ManifestRow } from '@/api/types'
import { ErrorNote, Loading } from '@/components/common/Panels'
import { Pill, TierChip } from '@/components/common/StatusChip'
import { Button } from '@/components/ui/button'
import { useManifest } from '@/hooks/queries'
import { pnrTail } from '@/lib/format'

function Row({ vehicleId, row }: { vehicleId: string; row: ManifestRow }) {
  const qc = useQueryClient()
  const board = useMutation({
    mutationFn: () => boardGroup(vehicleId, { allocation_id: row.allocation_id }),
    onSettled: () => { for (const k of ['field', 'passengers', 'capacity', 'state']) void qc.invalidateQueries({ queryKey: [k] }) },
  })
  return (
    <li className="rounded-lg border bg-card px-3 py-3" data-testid={`manifest-${row.group_id}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-base font-semibold">
            <span className="font-mono">{row.group_id}</span>
            <span className="font-normal text-ink-2"> · {row.size === 1 ? '1 person' : `group of ${row.size}`}</span>
            {row.tier != null && <TierChip tier={row.tier} name={row.tier_name} />}
          </div>
          <div className="font-mono text-sm text-ink-2">{row.pnr ? `PNR ${pnrTail(row.pnr)}` : 'UTS · unreserved'} · {row.class}</div>
          <div className="mt-0.5 text-base">to {row.dest_name ?? row.dest_place} {row.wheelchair && <Pill tone="info" className="ml-1">wheelchair</Pill>}</div>
        </div>
        {row.status === 'BOARDED' ? (
          <span className="shrink-0 rounded-lg border-2 border-boarded bg-boarded/10 px-3 py-2 text-base font-semibold text-boarded">✓ Boarded</span>
        ) : (
          <Button variant="outline" size="lg" className="h-12 shrink-0 border-2 font-semibold" disabled={!row.can_board || board.isPending} onClick={() => board.mutate()}>
            {board.isPending ? '…' : 'Mark boarded'}
          </Button>
        )}
      </div>
      {row.note && <p className="mt-1 text-sm text-tentative-ink">{row.note}</p>}
      <ErrorNote error={board.error} />
    </li>
  )
}

export function Manifest({ vehicleId }: { vehicleId: string }) {
  const { data, error } = useManifest(vehicleId)
  return (
    <section className="px-4 py-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">Allocated passengers</h2>
        {data && <span className="font-mono text-base text-ink-2" data-testid="boarded-count">{data.boarded_heads} / {data.expected_heads} boarded</span>}
      </div>
      <ErrorNote error={error} />
      {!data && !error && <Loading what="manifest" />}
      {data && data.passengers.length === 0 && <p className="py-3 text-base text-ink-2">Nobody is allocated to this vehicle yet.</p>}
      <ul className="mt-2 max-h-[52vh] space-y-2 overflow-y-auto pr-1" tabIndex={0} aria-label="Allocated passengers">
        {data?.passengers.map((r) => <Row key={r.allocation_id} vehicleId={vehicleId} row={r} />)}
      </ul>
      {data && <p className="mt-2 text-sm text-ink-2">Counts are people, not groups. Only confirmed passengers can be marked boarded.</p>}
    </section>
  )
}
