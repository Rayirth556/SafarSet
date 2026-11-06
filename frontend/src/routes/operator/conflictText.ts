import type { FieldConflict } from '@/api/types'
import { hhmm } from '@/lib/format'

/** What happened, in the operator's words. The engine's rule is the same in every case: the reading taken later wins. */
export function conflictSentence(c: FieldConflict): string {
  const seats = (n: number) => `${n} seat${n === 1 ? '' : 's'}`
  switch (c.outcome) {
    case 'CONFLICT':
      return `Two readings at ${hhmm(c.kept_observed_at)} disagree: ${seats(c.kept_value)} and ${seats(c.other_value)}. The lower figure is in force until someone checks.`
    case 'STALE_IGNORED':
      return `A reading from ${hhmm(c.other_observed_at)} (${seats(c.other_value)}) arrived after a newer one and was refused. ${seats(c.kept_value)} from ${hhmm(c.kept_observed_at)} stays in force.`
    case 'UNDATED_IGNORED':
      return `A report with no reading time (${seats(c.other_value)}) was refused, because a timed reading (${seats(c.kept_value)} at ${hhmm(c.kept_observed_at)}) is in force.`
  }
}
