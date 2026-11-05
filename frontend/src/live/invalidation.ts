import type { QueryKey } from '@tanstack/react-query'
import type { Topic } from '@/api/types'

/** Every server-state query key in the app. Keys are prefixes: ['field'] covers vehicles and every manifest. */
export const qk = {
  state: ['state'] as const,          // clock, banner, KPIs, pending-batch summary, sim params (also the WS snapshot)
  capacity: ['capacity'] as const,
  passengers: ['passengers'] as const,
  why: ['why'] as const,
  unresolved: ['unresolved'] as const,
  batch: ['batch'] as const,          // ['batch','pending'], ['batch','list']
  field: ['field'] as const,          // ['field','vehicles'], ['field','manifest', id]
  rules: ['rules'] as const,
  phone: ['phone'] as const,          // ['phone', key]
  sim: ['sim'] as const,              // ['sim','params'], ['sim','timeline']
  events: ['events'] as const,
  notifier: ['notifier'] as const,
}

const ALL: QueryKey[] = Object.values(qk)

/** Invalidate hint topic -> the queries to refetch (docs/api.md section 5). KPIs live inside the state query. */
export const TOPIC_KEYS: Record<Topic, readonly QueryKey[]> = {
  banner: [qk.state],
  kpis: [qk.state],
  capacity: [qk.capacity, ['field', 'vehicles']],
  passengers: [qk.passengers, qk.why],
  unresolved: [qk.unresolved],
  batch: [qk.batch],
  field: [qk.field],
  rules: [qk.rules],
  phone: [qk.phone],
  sim: [qk.sim, qk.state],
  all: ALL,
}

export function keysForTopics(topics: readonly Topic[]): QueryKey[] {
  if (topics.includes('all')) return ALL
  const seen = new Map<string, QueryKey>()
  for (const t of topics) for (const k of TOPIC_KEYS[t] ?? []) seen.set(JSON.stringify(k), k)
  return [...seen.values()]
}

export const ALL_KEYS = ALL
