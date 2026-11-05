import { TrainFront } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import type { PhoneMessage } from '@/api/types'
import { AppHeader } from '@/components/common/AppHeader'
import { ErrorNote, Loading, NoScenario } from '@/components/common/Panels'
import { useLoaded, useNotifier, usePassengers, usePhoneThread } from '@/hooks/queries'
import { useAppState } from '@/hooks/useAppState'
import { pnrTail } from '@/lib/format'
import { usePhoneSocket } from './usePhoneSocket'

/** Show a language badge unless the phone mock is English-only and the message is English (then there is nothing to choose between). */
export const showLangBadge = (englishOnly: boolean, lang: string) => !(englishOnly && lang === 'en')

const LANG: Record<string, string> = { en: 'English', ta: 'தமிழ்' }

function Bubble({ m, englishOnly }: { m: PhoneMessage; englishOnly: boolean }) {
  const d = m.detail
  return (
    <li className="max-w-[88%] self-start">
      <div className="rounded-2xl rounded-bl-md border bg-card px-4 py-3 text-base leading-snug shadow-sm" lang={m.lang} data-testid="sms">
        {m.message}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-2 px-1 text-[13px] text-ink-2">
        {showLangBadge(englishOnly, m.lang) && <span className="rounded bg-secondary px-1.5 py-0.5 font-medium">{LANG[m.lang] ?? m.lang}</span>}
        {d?.draft_translation && <span className="text-tentative-ink">Draft translation, needs native review</span>}
        {d?.chars != null && <span className="font-mono">{d.chars} chars{d.segments != null && ` · ${d.segments} SMS`}</span>}
      </div>
    </li>
  )
}

function Thread({ id }: { id: string }) {
  const { data, error } = usePhoneThread(id)
  const { data: notifier } = useNotifier()
  usePhoneSocket(id, useLoaded())
  const end = useRef<HTMLDivElement>(null)
  const count = data?.messages.length ?? 0
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })      // no return value: some browsers return a Promise, which React rejects from an effect
  }, [count])
  const englishOnly = notifier?.phone_mock_english_only ?? false

  return (
    <div className="flex h-[640px] w-[360px] max-w-full flex-col overflow-hidden rounded-[2.2rem] border-[10px] border-ink bg-page shadow-xl" data-testid="phone">
      <div className="flex items-center gap-3 border-b bg-card px-4 py-3">
        <div className="grid size-11 place-items-center rounded-full bg-boarded/10 text-boarded"><TrainFront className="size-6" aria-hidden /></div>
        <div>
          <div className="text-lg font-semibold leading-tight">SafarSet</div>
          <div className="text-sm text-ink-2">SMS · read-only demo</div>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-4">
        {error && (error as { kind?: string }).kind === 'NotFound'
          ? <p className="text-center text-base text-ink-2" role="alert">No passenger has the PNR or group id “{id}”.</p>
          : <ErrorNote error={error} />}
        {!data && !error && <Loading what="messages" />}
        {data && count === 0 && (
          <p className="mt-10 text-center text-base text-ink-2" data-testid="empty-thread">No messages yet. Messages arrive here once the operator approves a plan.</p>
        )}
        <ul className="flex flex-col gap-3">
          {data?.messages.map((m) => <Bubble key={m.id} m={m} englishOnly={englishOnly} />)}
        </ul>
        <div ref={end} />
      </div>
    </div>
  )
}

/** Lists passengers so a phone can be chosen. Only used when no id is in the URL or the toolbar is on. */
function PassengerPicker({ value }: { value: string | undefined }) {
  const navigate = useNavigate()
  const { data } = usePassengers({ limit: 200 })
  return (
    <label className="flex flex-wrap items-center gap-3 text-base">
      <span className="font-medium">Viewing as</span>
      <select className="h-11 min-w-72 rounded-lg border bg-card px-3 text-base" value={value ?? ''} onChange={(e) => e.target.value && navigate(`/phone/${encodeURIComponent(e.target.value)}`)}>
        <option value="">Choose a passenger…</option>
        {data?.items.map((p) => (
          <option key={p.group_id} value={p.pnr ?? p.group_id}>
            {p.group_id} · {p.pnr ? `PNR ${pnrTail(p.pnr)}` : 'unreserved'} · to {p.dest_name ?? p.dest_place} · {p.state.toLowerCase()}
          </option>
        ))}
      </select>
    </label>
  )
}

export function PhonePage() {
  const { id } = useParams()
  const [params] = useSearchParams()
  const { data: state } = useAppState()
  const bare = params.has('bare')
  return (
    <>
      {!bare && <AppHeader subtitle="Passenger phone (mock)" />}
      <main className="flex flex-col items-center gap-5 px-4 py-6">
        {state && !state.loaded && <NoScenario />}
        {state?.loaded && (
          <>
            {!bare && <PassengerPicker value={id} />}
            {id ? <Thread key={id} id={id} /> : <p className="text-base text-ink-2">Choose a passenger to see their messages.</p>}
          </>
        )}
      </main>
    </>
  )
}
