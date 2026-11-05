import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { putRules } from '@/api/endpoints'
import type { Rules } from '@/api/types'
import { Card, ErrorNote, Eyebrow, Loading } from '@/components/common/Panels'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useRules } from '@/hooks/queries'
import { byPoints, factorLabel } from '@/lib/labels'
import { parseDraft, toDraft, WeightsEditor, type WeightsDraft } from './WeightsEditor'

const BUFFER_LABEL: Record<string, string> = { MTC_BUS: 'MTC buses', INTERCITY_BUS: 'Intercity buses', TRAIN_UNRESERVED: 'Unreserved coaches' }
const pretty = (k: string) => (k.charAt(0).toUpperCase() + k.slice(1)).replace(/_/g, ' ')
const show = (v: unknown): string =>
  v !== null && typeof v === 'object' ? Object.entries(v).map(([k, x]) => `${k.toLowerCase()} ${x}`).join(', ') : String(v)

export function RulesPanel() {
  const qc = useQueryClient()
  const { data: rules, error } = useRules()
  const [editing, setEditing] = useState(false)
  const [weights, setWeights] = useState<WeightsDraft>({})
  const [buffers, setBuffers] = useState<Record<string, string>>({})
  const [localError, setLocalError] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: (b: Parameters<typeof putRules>[0]) => putRules(b),
    onSuccess: () => setEditing(false),
    onSettled: () => { for (const k of ['rules', 'batch', 'capacity', 'state']) void qc.invalidateQueries({ queryKey: [k] }) },
  })

  const start = (r: Rules) => {
    setWeights(toDraft(r.weights))
    setBuffers(Object.fromEntries(Object.entries(r.buffers).map(([m, b]) => [m, String(Math.round((b.buffer_pct ?? 0) * 100))])))
    setLocalError(null)
    save.reset()
    setEditing(true)
  }
  const submit = (r: Rules) => {
    const w = parseDraft(weights)
    if ('error' in w) return setLocalError(w.error)
    const body: Parameters<typeof putRules>[0] = {}
    if (Object.keys(r.weights).some((k) => r.weights[k] !== w.weights[k])) body.weights = w.weights
    const changed: Record<string, number> = {}
    for (const [m, s] of Object.entries(buffers)) {
      const pct = Number(s)
      if (s.trim() === '' || !Number.isFinite(pct) || pct < 0 || pct > 100) return setLocalError(`${BUFFER_LABEL[m] ?? m}: enter a percentage from 0 to 100`)
      if (Math.round((r.buffers[m].buffer_pct ?? 0) * 100) !== pct) changed[m] = pct / 100
    }
    if (Object.keys(changed).length) body.buffers = changed
    setLocalError(null)
    if (!body.weights && !body.buffers) return setEditing(false)
    save.mutate(body)
  }

  return (
    <Card
      title="Rules in force"
      aside={rules && (editing
        ? <span className="flex gap-2"><Button variant="outline" onClick={() => setEditing(false)}>Cancel</Button><Button className="font-semibold" disabled={save.isPending} onClick={() => submit(rules)}>Save</Button></span>
        : <Button variant="outline" onClick={() => start(rules)}>Edit</Button>)}
    >
      <ErrorNote error={error} />
      {!rules && !error && <Loading what="rules" />}
      {rules && (
        <div className="space-y-4">
          <div>
            <Eyebrow>Priority weights · {rules.weights_source === 'operator' ? 'set by operator' : 'defaults (placeholders)'}</Eyebrow>
            {editing ? (
              <WeightsEditor value={weights} onChange={setWeights} />
            ) : (
              <div className="divide-y">
                {byPoints(rules.weights).map(([k, v]) => (
                  <div key={k} className="flex justify-between py-1.5 text-base">
                    <span>{factorLabel(k)}</span><span className="font-mono font-semibold text-boarded">+{v}</span>
                  </div>
                ))}
              </div>
            )}
            <p className="mt-1 text-sm text-ink-2">Changing weights does not touch the current plan. Use “Adjust weights &amp; re-run” on the approval panel to apply them.</p>
          </div>

          <div>
            <Eyebrow>Capacity buffer</Eyebrow>
            <div className="divide-y">
              <div className="flex justify-between py-1.5 text-base"><span>Reserved coaches</span><span className="font-mono">exact (no buffer)</span></div>
              {Object.entries(rules.buffers).map(([m, b]) => (
                <div key={m} className="flex items-center justify-between gap-3 py-1.5 text-base">
                  <span>{BUFFER_LABEL[m] ?? pretty(m)} <span className="font-mono text-sm text-ink-2">{b.example}</span></span>
                  {editing ? (
                    <span className="flex items-center gap-1">
                      <Input inputMode="numeric" className="h-10 w-20 text-right font-mono text-base" value={buffers[m] ?? ''} onChange={(e) => setBuffers({ ...buffers, [m]: e.target.value })} aria-label={`${BUFFER_LABEL[m] ?? m} buffer percent`} />%
                    </span>
                  ) : <span className="font-mono font-semibold">{Math.round((b.buffer_pct ?? 0) * 100)}%</span>}
                </div>
              ))}
            </div>
            <p className="mt-1 text-sm text-ink-2">A buffer below what is already confirmed or boarded is refused; nothing changes.</p>
          </div>

          <div>
            <Eyebrow>Allocator settings · read only</Eyebrow>
            <div className="divide-y">
              {Object.entries(rules.config).filter(([k]) => !k.startsWith('_')).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3 py-1.5 text-base">
                  <span>{pretty(k)}</span><span className="text-right font-mono">{show(v)}</span>
                </div>
              ))}
            </div>
          </div>
          {localError && <p role="alert" className="text-base text-unresolved-ink">{localError}</p>}
          <ErrorNote error={save.error} />
        </div>
      )}
    </Card>
  )
}
