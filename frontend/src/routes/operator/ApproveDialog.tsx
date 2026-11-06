import { useState } from 'react'
import type { PhoneKind } from '@/api/types'
import { ErrorNote } from '@/components/common/Panels'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useBatchPreview, useCapacity } from '@/hooks/queries'
import { plural } from '@/lib/format'
import { SMS_KIND_LABEL } from '@/lib/labels'
import { nameOf, useVehicleIndex } from '@/lib/vehicles'
import { cn } from '@/lib/utils'

const LANGS = [{ code: 'en', label: 'English' }, { code: 'ta', label: 'தமிழ்' }] as const
const LANG_NAME: Record<string, string> = { en: 'English', ta: 'Tamil' }
const KINDS: PhoneKind[] = ['NEW', 'CHANGED', 'DISPLACED_UNPLACED']

const chip = (on: boolean) => cn('h-10 rounded-lg border-2 px-3 text-base font-semibold', on ? 'border-navy bg-navy text-white' : 'border-line bg-card text-ink')

/**
 * The last look before approving. Every group gets its OWN message (its vehicle, departure time and boarding point), so the dialog does not
 * show one message for everybody: pick a kind of message (a new journey, a changed one, a lost seat) and a vehicle, and it shows the real text
 * the best-scored group on that vehicle would get, in English or Tamil. The server renders it with the same code that sends it. Nothing is sent
 * by looking.
 */
export function ApproveDialog({ open, onClose, batchId, summary, onApprove, pending, error }: {
  open: boolean; onClose: () => void; batchId: string; summary: string; onApprove: () => void; pending: boolean; error: Error | null
}) {
  const [lang, setLang] = useState<string>('en')
  const [kind, setKind] = useState<PhoneKind | undefined>(undefined)
  const [vehicleId, setVehicleId] = useState<string | undefined>(undefined)
  const { data: preview, error: previewError } = useBatchPreview(batchId, kind, lang, open, vehicleId)
  const { data: capacity } = useCapacity('ALLOCATION')
  const names = useVehicleIndex()
  const sample = preview?.sample ?? null
  const messages = preview?.will_send?.total
  const languages = Object.entries(preview?.by_language ?? {})

  // vehicles that have a message of the shown kind, earliest departure first
  const departs = new Map(capacity?.map((v) => [v.vehicle_id, { at: v.depart_min, text: v.depart }]))
  const byVehicle = preview?.by_vehicle
  const perVehicle = Object.entries(byVehicle?.[sample?.kind ?? 'NEW'] ?? {})
    .sort(([a], [b]) => (departs.get(a)?.at ?? 0) - (departs.get(b)?.at ?? 0) || a.localeCompare(b))
  const journeys = new Set(KINDS.flatMap((k) => Object.keys(byVehicle?.[k] ?? {}))).size

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      {/* one column that may not grow past the dialog: without minmax(0,1fr) the long vehicle names in the dropdown widen it and the content spills out */}
      <DialogContent className="grid-cols-[minmax(0,1fr)] text-base sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="text-xl">Approve plan {batchId}?</DialogTitle>
          <DialogDescription className="text-base">{summary} This freezes the plan and cannot be undone.</DialogDescription>
        </DialogHeader>

        <div>
          <div className="text-sm font-semibold uppercase tracking-wide text-ink-2">What passengers will receive</div>
          <p className="mb-2 text-base" data-testid="own-message-note">
            Each group gets its own message with its own vehicle, time and boarding point
            {journeys > 0 && <> ({plural(journeys, 'vehicle')} in this plan)</>}. Choose one to see the exact text.
          </p>
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Kind of message">
            {KINDS.filter((k) => (preview?.will_send?.[k] ?? 0) > 0).map((k) => (
              <button key={k} className={chip(sample?.kind === k)} aria-pressed={sample?.kind === k} onClick={() => { setKind(k); setVehicleId(undefined) }}>
                {SMS_KIND_LABEL[k]} <span className="font-mono font-normal">{preview?.will_send?.[k]}</span>
              </button>
            ))}
            <span className="ml-auto flex gap-1" role="group" aria-label="Language">
              {LANGS.map((l) => <button key={l.code} className={chip(lang === l.code)} aria-pressed={lang === l.code} onClick={() => setLang(l.code)}>{l.label}</button>)}
            </span>
          </div>
          {perVehicle.length > 0 && (
            <label className="mt-2 flex items-center gap-2 text-base">
              <span className="shrink-0">Example for</span>
              <select className="h-11 min-w-0 flex-1 rounded-lg border bg-card px-3 text-base" value={sample?.vehicle_id ?? ''} onChange={(e) => setVehicleId(e.target.value)} data-testid="preview-vehicle">
                {perVehicle.map(([id, n]) => (
                  <option key={id} value={id}>{departs.get(id)?.text ?? '--:--'} · {plural(n, 'message')} · {nameOf(names, id)}</option>
                ))}
              </select>
            </label>
          )}
        </div>

        <div className="rounded-xl bg-page px-3 py-4" data-testid="sms-preview">
          {!sample && !previewError && <p className="text-ink-2">Loading the message…</p>}
          <ErrorNote error={previewError} />
          {sample && (
            <>
              <div lang={sample.lang} className="max-w-[92%] rounded-2xl rounded-bl-md border bg-card px-4 py-3 leading-snug shadow-sm" data-testid="sms-preview-text">
                {sample.message}
              </div>
              <p className="mt-2 px-1 text-sm text-ink-2">
                One example: {sample.group_id} (group of {sample.size}) · {sample.chars} characters · {sample.segments} SMS
              </p>
              {sample.draft_translation && (
                <p className="mt-1 px-1 text-sm text-tentative-ink">Draft translation: a native Tamil speaker must review it before any real use.</p>
              )}
            </>
          )}
        </div>
        {languages.length > 0 && (
          <p className="text-sm text-ink-2">
            {messages} {messages === 1 ? 'message goes' : 'messages go'} out, one per group, each in the passenger's own language: {languages.map(([c, n]) => `${n} ${LANG_NAME[c] ?? c}`).join(', ')}.
          </p>
        )}

        <ErrorNote error={error} />
        {error && (error as { kind?: string }).kind === 'StaleBatch' && <p className="text-base">The plan is out of date. Close this and re-plan.</p>}
        <DialogFooter>
          <Button variant="outline" size="lg" onClick={onClose}>Cancel</Button>
          <Button size="lg" className="font-semibold" onClick={onApprove} disabled={pending} data-testid="confirm-approve">
            {pending ? 'Approving…' : messages != null ? `Approve and send ${messages} ${messages === 1 ? 'message' : 'messages'}` : 'Approve and send messages'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
