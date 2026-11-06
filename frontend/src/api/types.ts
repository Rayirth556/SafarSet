// Response and request shapes of the SafarSet backend. Source of truth: docs/api.md and backend/safarset/api/{views,models}.py.
// Times: `*_min` are minutes of the scenario day, with an HH:MM twin. Everything in the demo is SIMULATED.

export type Hhmm = string
export interface Heads { groups: number; heads: number }

export type GroupState = 'UNAFFECTED' | 'UNRESOLVED' | 'TENTATIVE' | 'CONFIRMED' | 'BOARDED'
export type DiffCategory = 'DISPLACED' | 'NEWLY_PLACED' | 'RESHUFFLED' | 'PLACED' | 'UNRESOLVED'
export type LoadLevel = 'NORMAL' | 'FULL' | 'OVERCROWDED'

// ---------------------------------------------------------------------------------------------- state / KPIs / banner
export interface Composition {
  pnr_heads: number
  ticketed_unreserved_heads: number
  /** estimate of unregistered walk-ons; NOT part of `affected` */
  unreserved_estimate: { heads: number; estimated: true }
}
export interface PriorityOverview {
  tier_0: Heads
  tier_1: Heads
  tier_2: Heads
  accommodated: Heads
  unresolved: Heads
  available_capacity: number
}

export interface Kpis {
  affected: Heads
  tentative: Heads
  confirmed: Heads
  boarded: Heads
  unresolved: Heads
  displaced_awaiting_replacement: Heads
  held_by_operator: Heads
  composition: Composition
  priority_overview?: PriorityOverview
}
export interface BannerItem {
  seq: number
  kind: 'TRAIN_CANCELLED' | 'TRAIN_DELAYED' | 'ROAD_CLOSED'
  vehicle_id?: string
  route_id?: string | null
  text: string
}
export interface Banner {
  active: boolean
  title: string
  items: BannerItem[]
  clock: Hhmm | null
  label?: string
  cancelled_vehicle_id?: string
}
export interface SimParams { compliance_rate: number; walkon_rate: number }
export interface PendingBatchSummary {
  batch_id: string
  cause: string
  stale: boolean
  weights_out_of_date: boolean
  diff: Record<DiffCategory, Heads>
  allocations: { tentative: Heads; confirmed: Heads }
}
export interface LoadedState {
  loaded: true
  last_seq: number
  clock: Hhmm
  clock_min: number
  banner: Banner
  kpis: Kpis
  pending_batch: PendingBatchSummary | null
  sim_params: SimParams
}
/** `GET /api/state` (and the WS snapshot). Before any scenario is loaded only `loaded: false` is known. */
export type AppState = LoadedState | { loaded: false; last_seq: number }

// ---------------------------------------------------------------------------------------------- capacity
export interface Segment {
  seg_idx: number
  from_stop: string
  to_stop: string
  cap: number
  confirmed: number
  boarded: number
  tentative: number
  free: number
}
export interface FieldReport { level: LoadLevel; count: number | null; seq: number }
export interface Pool {
  pool_id: string
  kind: 'RESERVED' | 'UNRESERVED'
  class: string
  coaches: number
  nominal: number
  capacity_label: string
  buffer_mode: string | null
  buffer_pct: number | null
  formula: string
  walkon_expected: number
  field_report: FieldReport | null
  segments: Segment[]
}
export interface Vehicle {
  vehicle_id: string
  mode: string
  role: 'ALLOCATION' | 'TRANSFER_LEG'
  label: string
  name: string | null
  train_no: string | null
  route_id: string | null
  status: string
  delay_min: number
  depart_min: number
  depart: Hhmm
  boarding_note: string | null
  wheelchair_accessible: boolean | null
  stops: string[]
  pools: Pool[]
}

// ---------------------------------------------------------------------------------------------- passengers
export type ScoreBreakdown = [factor: string, points: number][]
export interface AllocationView {
  id: number
  status: 'TENTATIVE' | 'CONFIRMED' | 'BOARDED'
  pool_id: string
  vehicle_id: string
  board_idx: number
  alight_idx: number
  depart_min: number | null
  arrive_min: number | null
  depart: Hhmm | null
  arrive: Hhmm | null
  class_step: string | null
  class_flagged: boolean | null
  boarding_note: string | null
  score: number
}
export interface PassengerFlags {
  senior: boolean
  child: boolean
  pregnant: boolean
  disability: boolean
  wheelchair: boolean
  deadline: Hhmm | null
}
export interface Passenger {
  group_id: string
  pnr: string | null
  size: number
  class: string
  reserved: boolean
  known: boolean
  dest_place: string
  dest_name: string | null
  state: GroupState
  score: number | null
  rank: number | null
  score_breakdown: ScoreBreakdown | null
  tier?: number
  tier_name?: string
  tier_reason?: string | null
  escalated?: boolean
  effective_score?: number | null
  base_score?: number | null
  ageing?: number | null
  flags: PassengerFlags
  language: string | null
  waiting_since: number
  allocation: AllocationView | null
  displaced: boolean
  held_by_operator: boolean
  boarded_on_own: string | null
}
export interface PassengerPage { total: number; items: Passenger[] }
export interface PassengerQuery { status?: string; dest?: string; q?: string; limit?: number; offset?: number }

/** Machine-readable allocation / unresolved reason; `text` is the plain-language sentence. */
export interface Reason {
  text: string
  rank?: number
  of?: number
  score?: { total: number; breakdown: ScoreBreakdown }
  [k: string]: unknown
}
export type AlternativeType = 'LATE_ARRIVAL' | 'MULTI_LEG' | 'WAITLIST'
export interface Alternative {
  type: AlternativeType
  rank: number
  note?: string
  destination?: string
  position?: number
  [k: string]: unknown
}
export interface UnresolvedItem {
  group_id: string
  pnr: string | null
  size: number
  class: string
  rank: number | null
  score: number | null
  reason: Reason | null
  alternatives: Alternative[]
  displaced: boolean
  blocking_groups: string[] | null
  blocking_why: string | null
  planned_in_batch: string | null
}
export interface UnresolvedDest { dest_place: string; dest_name: string | null; groups: number; heads: number; items: UnresolvedItem[] }

export interface AllocationHistory {
  id: number
  pool_id: string
  vehicle_id: string
  board_idx: number
  alight_idx: number
  status: string
  batch_id: string | null
  score: number
  created_seq: number
  status_seq: number | null
  status_reason: Record<string, unknown> | null
}
export interface Why {
  group: {
    group_id: string; pnr: string | null; size: number; class: string; reserved: boolean; known: boolean
    dest_place: string; dest_name: string | null; requirements: Record<string, unknown>; attrs: Record<string, unknown>
  }
  state: GroupState
  score: { total: number; breakdown: ScoreBreakdown; [k: string]: unknown } | null
  rank: number | null
  of: number
  tier?: number
  tier_name?: string
  tier_reason?: string | null
  escalated?: boolean
  escalation_reason?: string | null
  base_score?: number | null
  effective_score?: number | null
  ageing?: number | null
  factor_scores?: Record<string, number>
  factor_weights?: Record<string, number>
  priority_policy?: Record<string, unknown>
  stored_score_at_allocation: number | null
  allocation: AllocationView | null
  reason: Reason | null
  decision_text: string
  unresolved: (Record<string, unknown> & { reason?: Reason; alternatives?: Alternative[]; blocking_groups?: string[]; blocking_why?: string; batch_id: string }) | null
  held_by_operator: { why: string; size: number } | null
  displaced: boolean
  boarded_on_own: string | null
  history: AllocationHistory[]
}

// ---------------------------------------------------------------------------------------------- batches
export interface BatchItem {
  group_id: string
  pnr: string | null
  size: number
  class: string
  dest_place: string
  dest_name: string | null
  /** DISPLACED: replaced, cause, old_sms_still_held, operator_override. RESHUFFLED: forced, moved_from.
   *  UNRESOLVED: reason, alternatives, blocking_*. Placements: vehicle_id, pool_id, arrive_min, class_step. */
  detail: Record<string, unknown> & {
    replaced?: boolean
    cause?: unknown
    old_sms_still_held?: boolean
    operator_override?: boolean
    forced?: boolean
    moved_from?: unknown
    reason?: Reason
    alternatives?: Alternative[]
    blocking_groups?: string[]
    blocking_why?: 'NO_ALTERNATIVE_WITHIN_TOLERANCE' | 'MOVES_AS_MANY_HEADS_AS_PLACED'
    blocking_moved_heads?: number
    blocking_placed_heads?: number
  }
}
export interface Batch {
  batch_id: string
  status: 'PROPOSED' | 'APPROVED' | string
  cause: string
  base_seq: number
  proposed_seq: number
  approved_seq: number | null
  stale: boolean
  weights_out_of_date: boolean
  diff: Record<DiffCategory, Heads>
  summary: Record<string, unknown>
  reshuffle_moves: unknown[]
  allocations: { tentative: Heads; confirmed: Heads }
  items?: Partial<Record<DiffCategory, BatchItem[]>>
}
export interface BatchRow { batch_id: string; status: string; cause: string; proposed_seq: number; approved_seq: number | null }
export interface ApproveResult { batch_id: string; seq: number; confirmed_groups: number; notified_groups: number }

// ---------------------------------------------------------------------------------------------- rules / events / notifier
export type Weights = Record<string, number>
export interface Rules {
  weights: Weights
  weights_version: number
  weights_source: string
  buffers: Record<string, { buffer_pct: number | null; example: string }>
  class_rank: string[]
  config: Record<string, unknown>
  priority_policy?: Record<string, unknown>
  editable: { weights: boolean; buffers: boolean; config: boolean }
  note: string
}
export interface SafarEvent {
  seq: number
  ts_sim: number
  ts_wall: string
  type: string
  actor: string
  payload: Record<string, unknown>
  causation_seq: number | null
  rejected: boolean
}
export interface EventsPage { hide_rejected: boolean; last_seq: number; events: SafarEvent[] }
export interface EventsQuery { after?: number; limit?: number; hide_rejected?: boolean; tail?: boolean }
export interface NotifierStatus {
  phone_mock: boolean
  phone_mock_english_only: boolean
  sms: { enabled: boolean; note: string; tamil_allowed: boolean }
  languages: string[]
  tamil_review_status: string
}
export type OverrideAction = 'ASSIGN' | 'UNASSIGN' | 'RESUME_AUTO'
export interface OverrideBody { action: OverrideAction; reason: string; pool_id?: string; board_idx?: number; alight_idx?: number }

// ---------------------------------------------------------------------------------------------- field view
export interface FieldVehicle {
  vehicle_id: string
  mode: string
  label: string
  name: string | null
  train_no: string | null
  route_id: string | null
  status: string
  depart: Hhmm
  delay_min: number
  boarding_note: string | null
  pools: { pool_id: string; kind: 'RESERVED' | 'UNRESERVED'; class: string; nominal: number; field_report: FieldReport | null }[]
}
export interface ManifestRow {
  allocation_id: number
  group_id: string
  pnr: string | null
  size: number
  class: string
  pool_id: string
  status: 'TENTATIVE' | 'CONFIRMED' | 'BOARDED'
  dest_place: string
  dest_name: string | null
  wheelchair: boolean
  can_board: boolean
  note: string | null
  tier?: number
  tier_name?: string
}
export interface Manifest {
  vehicle_id: string
  status: string
  depart: Hhmm
  expected_heads: number
  boarded_heads: number
  passengers: ManifestRow[]
}
export interface LoadReportBody { level: LoadLevel; count?: number; pool_id?: string }
export interface VacancyBody { pool_id: string; from_seg: number; to_seg: number; vacancy: number }

// ---------------------------------------------------------------------------------------------- phone mock
export type PhoneKind = 'NEW' | 'CHANGED' | 'DISPLACED_UNPLACED'
export interface PhoneMessage {
  id: number
  channel: string
  lang: string
  message: string
  reason: string | null
  detail: { chars?: number; encoding?: string; segments?: number; preferred_language?: string; draft_translation?: boolean; kind?: PhoneKind } | null
  sent_seq: number
  /** simulation clock when it was sent */
  sent_at: Hhmm | null
  sent_at_min: number | null
  /** null on logs written before the field existed */
  kind: PhoneKind | null
}
export interface PhoneThread { group_id: string; pnr: string | null; messages: PhoneMessage[] }

// ---------------------------------------------------------------------------------------------- demo controls (/sim)
export interface LoadScenarioBody {
  seed?: number
  n_passengers?: number
  pct_senior?: number
  pct_groups?: number
  compliance_rate?: number
  walkon_rate?: number
  pct_unreserved?: number
  n_mtc_specials?: number
  n_intercity_specials?: number
  cancel_time?: string
  exclude_trains?: string[]
}
export interface LoadScenarioResult {
  label: string
  params: Record<string, unknown>
  warnings: string[]
  cancelled_vehicle_id: string
  clock: Hhmm
  groups: number
  heads: number
  vehicles: number
  timeline_steps: number
}
export interface SimResult { seq?: number; batch_id?: string | null; confirmed_groups?: number; notified_groups?: number }
export interface TimelineStep {
  step: number
  label: string
  at: Hhmm
  at_min: number
  kind: string
  type: string
  payload: Record<string, unknown>
  expect: Record<string, unknown>
}
export interface Timeline { label: string; next_step: number; total: number; steps: TimelineStep[] }
export interface TimelineNextResult {
  played: Pick<TimelineStep, 'step' | 'label' | 'at' | 'kind' | 'type'>
  result: SimResult
  next_step: number
}
export interface DepartResult {
  vehicle_id: string
  boarded_groups: string[]
  refused_groups: string[]
  rusher_groups: string[]
  load_report: Record<string, unknown> | null
  batch_id: string | null
  params: SimParams
}

// ---------------------------------------------------------------------------------------------- live stream (WS /ws)
export type Topic =
  | 'banner' | 'capacity' | 'passengers' | 'unresolved' | 'batch' | 'kpis' | 'field' | 'rules' | 'phone' | 'sim' | 'all'

export type WsMessage =
  | ({ type: 'snapshot' | 'reset' } & AppState)
  | { type: 'event'; seq: number; event: SafarEvent }
  | { type: 'kpis'; kpis: Kpis; clock: Hhmm; clock_min: number; last_seq: number }
  | { type: 'invalidate'; topics: Topic[]; last_seq: number }
  | { type: 'pong'; last_seq: number }
  | { type: 'clock' }
