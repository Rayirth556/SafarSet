import { describe, expect, it } from 'vitest'
import type { Topic } from '@/api/types'
import { ALL_KEYS, keysForTopics, TOPIC_KEYS } from './invalidation'

const names = (topics: Topic[]) => keysForTopics(topics).map((k) => k.join('/'))

describe('keysForTopics', () => {
  it('covers every topic in docs/api.md', () => {
    const documented: Topic[] = ['banner', 'capacity', 'passengers', 'unresolved', 'batch', 'kpis', 'field', 'rules', 'phone', 'sim', 'conflicts', 'all']
    expect(Object.keys(TOPIC_KEYS).sort()).toEqual([...documented].sort())
  })
  it('maps a cancellation hint to the operator queries', () => {
    expect(names(['banner', 'capacity', 'passengers', 'unresolved', 'batch', 'kpis'])).toEqual(
      expect.arrayContaining(['state', 'capacity', 'field/vehicles', 'passengers', 'why', 'unresolved', 'batch']))
  })
  it('why follows passengers; the field manifest follows the field topic', () => {
    expect(names(['passengers'])).toContain('why')
    expect(names(['field'])).toEqual(['field'])
  })
  it('"all" refetches every key and de-duplicates', () => {
    expect(keysForTopics(['all', 'batch'])).toBe(ALL_KEYS)
    expect(names(['banner', 'kpis'])).toEqual(['state'])
  })
  it('ignores a topic it does not know instead of throwing', () => {
    expect(names(['nonsense' as Topic])).toEqual([])
  })
})
