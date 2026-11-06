import { describe, expect, it } from 'vitest'
import type { FieldConflict } from '@/api/types'
import { conflictSentence } from './conflictText'

const base: FieldConflict = {
  id: 1, seq: 10, pool_id: 'TRAIN-SIM-CXL:3A', seg_idx: 2, outcome: 'STALE_IGNORED',
  kept_value: 2, kept_source: 'field view (HHT)', kept_observed_at: 855,
  other_value: 9, other_source: 'field view (HHT)', other_observed_at: 845,
  resolved: false, resolved_seq: null, resolved_note: null,
}

describe('conflictSentence', () => {
  it('explains a refused older reading with both times', () => {
    expect(conflictSentence(base)).toBe(
      'A reading from 14:05 (9 seats) arrived after a newer one and was refused. 2 seats from 14:15 stays in force.')
  })

  it('says the lower figure is in force for a same-time disagreement', () => {
    const text = conflictSentence({ ...base, outcome: 'CONFLICT', kept_value: 3, other_value: 6, other_observed_at: 855, kept_source: 'conflict' })
    expect(text).toBe('Two readings at 14:15 disagree: 3 seats and 6 seats. The lower figure is in force until someone checks.')
  })

  it('explains an undated report that was refused', () => {
    const text = conflictSentence({ ...base, outcome: 'UNDATED_IGNORED', other_value: 1, other_observed_at: null })
    expect(text).toContain('no reading time (1 seat)')
    expect(text).toContain('14:15')
  })

  it('uses the singular for one seat', () => {
    expect(conflictSentence({ ...base, kept_value: 1 })).toContain('1 seat from')
  })
})
