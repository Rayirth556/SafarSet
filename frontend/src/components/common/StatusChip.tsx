import type { ReactNode } from 'react'
import type { GroupState } from '@/api/types'
import { STATE_LABEL } from '@/lib/labels'
import { cn } from '@/lib/utils'

const STYLE: Record<GroupState, string> = {
  UNAFFECTED: 'bg-secondary text-ink-2',
  UNRESOLVED: 'bg-unresolved/10 text-unresolved-ink',
  TENTATIVE: 'bg-tentative/15 text-tentative-ink',
  CONFIRMED: 'bg-confirmed/15 text-confirmed-ink',
  BOARDED: 'bg-boarded/10 text-boarded',
}

export function StatusChip({ state, className }: { state: GroupState; className?: string }) {
  return <span className={cn('inline-block rounded-md px-2 py-0.5 text-sm font-semibold', STYLE[state], className)}>{STATE_LABEL[state]}</span>
}

const TONES = {
  neutral: 'bg-secondary text-ink-2',
  warn: 'bg-tentative/15 text-tentative-ink',
  bad: 'bg-unresolved/10 text-unresolved-ink',
  info: 'bg-boarded/10 text-boarded',
}

export function Pill({ children, tone = 'neutral', className }: { children: ReactNode; tone?: keyof typeof TONES; className?: string }) {
  return <span className={cn('inline-block rounded-md px-2 py-0.5 text-sm font-medium', TONES[tone], className)}>{children}</span>
}
