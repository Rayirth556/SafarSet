import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { resolveConflict } from '@/api/endpoints'
import type { FieldConflict } from '@/api/types'
import { Card, ErrorNote, Loading } from '@/components/common/Panels'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useConflicts } from '@/hooks/queries'
import { conflictSentence } from './conflictText'
import { qk } from '@/live/invalidation'

function ConflictRow({ c }: { c: FieldConflict }) {
  const qc = useQueryClient()
  const [note, setNote] = useState('')
  const review = useMutation({
    mutationFn: () => resolveConflict(c.id, { note: note.trim() }),
    onSuccess: () => setNote(''),
    onSettled: () => void qc.invalidateQueries({ queryKey: qk.conflicts }),
  })
  const tooShort = note.trim().length < 5
  return (
    <li className="space-y-2 py-3">
      <div className="text-sm font-semibold">{c.pool_id}, segment {c.seg_idx}</div>
      <p className="text-sm">{conflictSentence(c)}</p>
      <p className="text-xs text-muted-foreground">
        {c.kept_source !== 'conflict' && <>In force from {c.kept_source}. </>}
        Other report from {c.other_source}.
      </p>
      <div className="flex gap-2">
        <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why this value is right (at least 5 characters)" aria-label="Review note" />
        <Button className="font-semibold" disabled={tooShort || review.isPending} onClick={() => review.mutate()}>Mark reviewed</Button>
      </div>
      <ErrorNote error={review.error} />
    </li>
  )
}

export function ConflictsPanel() {
  const { data, error, isLoading } = useConflicts()
  const open = data?.items.filter((c) => !c.resolved) ?? []
  const reviewed = data?.items.filter((c) => c.resolved) ?? []
  return (
    <Card
      title="Field reports that disagree"
      aside={data && <span className="text-sm text-muted-foreground">{data.open} open</span>}
    >
      <ErrorNote error={error} />
      {isLoading && <Loading what="field conflicts" />}
      {data && data.items.length === 0 && <p className="text-sm text-muted-foreground">No field reports disagree.</p>}
      {open.length > 0 && <ul className="divide-y">{open.map((c) => <ConflictRow key={c.id} c={c} />)}</ul>}
      {reviewed.length > 0 && (
        <details className="mt-3 text-sm text-muted-foreground">
          <summary className="cursor-pointer">{reviewed.length} reviewed</summary>
          <ul className="mt-2 space-y-1">
            {reviewed.map((c) => (
              <li key={c.id}>{c.pool_id}, segment {c.seg_idx}: {c.resolved_note}</li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  )
}
