import { useLive, type LiveStatus } from '@/live/context'
import { useAppState } from '@/hooks/useAppState'
import { cn } from '@/lib/utils'

const STATUS: Record<LiveStatus, { text: string; dot: string }> = {
  live: { text: 'Live', dot: 'bg-confirmed' },
  connecting: { text: 'Connecting…', dot: 'bg-tentative' },
  resyncing: { text: 'Resyncing…', dot: 'bg-tentative' },
  reconnecting: { text: 'Reconnecting…', dot: 'bg-unresolved' },
}

export function AppHeader({ subtitle }: { subtitle: string }) {
  const { status } = useLive()
  const { data } = useAppState()
  const s = STATUS[status]
  return (
    <header className="border-b-[3px] border-saffron bg-navy text-white">
      <div className="flex items-center justify-between gap-4 px-6 py-3">
        <div>
          <div className="text-lg font-bold leading-tight">SafarSet</div>
          <div className="text-sm text-white/80">{subtitle}</div>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <span className="flex items-center gap-2"><span className={cn('size-2.5 rounded-full', s.dot)} />{s.text}</span>
          {data?.loaded && <span className="font-mono font-semibold">SIM {data.clock}</span>}
        </div>
      </div>
    </header>
  )
}
