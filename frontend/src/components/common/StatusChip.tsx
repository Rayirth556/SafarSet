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

const TIER_STYLES: Record<number, string> = {
  0: 'bg-red-500/15 text-red-700 dark:text-red-300 border border-red-500/30 font-bold',
  1: 'bg-amber-500/15 text-amber-800 dark:text-amber-300 border border-amber-500/30 font-semibold',
  2: 'bg-slate-500/10 text-slate-700 dark:text-slate-300 font-medium',
}

const TIER_NAMES: Record<number, string> = {
  0: 'Critical',
  1: 'High',
  2: 'Standard',
}

export function TierChip({ tier = 2, name, className }: { tier?: number; name?: string; className?: string }) {
  const label = name ?? TIER_NAMES[tier] ?? `Tier ${tier}`
  const style = TIER_STYLES[tier] ?? TIER_STYLES[2]
  return <span className={cn('inline-block rounded-md px-2 py-0.5 text-xs tracking-wide', style, className)}>{label}</span>
}
