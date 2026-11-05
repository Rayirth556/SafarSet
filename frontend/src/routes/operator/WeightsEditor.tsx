import type { Weights } from '@/api/types'
import { Input } from '@/components/ui/input'
import { byPoints, factorLabel } from '@/lib/labels'

export type WeightsDraft = Record<string, string>

/** Key order is the display order: highest points first, fixed when editing starts so rows do not jump while typing. */
export const toDraft = (w: Weights): WeightsDraft => Object.fromEntries(byPoints(w).map(([k, v]) => [k, String(v)]))

/** Returns the numeric weights, or an error message. The server needs the exact key set, so every key is kept. */
export function parseDraft(d: WeightsDraft): { weights: Weights } | { error: string } {
  const weights: Weights = {}
  for (const [k, s] of Object.entries(d)) {
    const n = Number(s)
    if (s.trim() === '' || !Number.isFinite(n) || n < 0) return { error: `${factorLabel(k)} must be a number, zero or more` }
    weights[k] = n
  }
  return { weights }
}

export function WeightsEditor({ value, onChange }: { value: WeightsDraft; onChange: (d: WeightsDraft) => void }) {
  return (
    <div className="divide-y">
      {Object.entries(value).map(([k, v]) => (
        <label key={k} className="flex items-center justify-between gap-4 py-2">
          <span className="text-base">{factorLabel(k)}</span>
          <Input
            inputMode="decimal"
            className="h-10 w-24 text-right font-mono text-base"
            value={v}
            onChange={(e) => onChange({ ...value, [k]: e.target.value })}
            aria-label={factorLabel(k)}
          />
        </label>
      ))}
    </div>
  )
}
