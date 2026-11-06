import { ApiError, get, post, put, qs } from './client'
import type {
  AppState, ApproveResult, Batch, BatchRow, Manifest, EventsPage, EventsQuery, FieldVehicle, LoadReportBody, LoadScenarioBody,
  LoadScenarioResult, NotifierStatus, OverrideBody, PassengerPage, PassengerQuery, PhoneThread, Rules, SimParams, SimResult, Timeline,
  TimelineNextResult, DepartResult, UnresolvedDest, Vehicle, VacancyBody, Why, Weights,
} from './types'

const enc = encodeURIComponent

// ------------------------------------------------------------------ operator (/api)
/** Before a scenario is loaded there is nothing to fetch. `/health` says so without a 409, which the browser would log as an error. */
export async function fetchState(): Promise<AppState> {
  const health = await get<{ scenario_loaded: boolean }>('/health')
  if (!health.scenario_loaded) return { loaded: false, last_seq: 0 }
  try {
    return await get<AppState>('/api/state')
  } catch (e) {
    if (e instanceof ApiError && e.kind === 'NoScenario') return { loaded: false, last_seq: 0 }   // lost a race with a restart
    throw e
  }
}
export const fetchCapacity = (role: 'ALLOCATION' | 'TRANSFER_LEG' | 'all' = 'ALLOCATION') => get<Vehicle[]>(`/api/capacity${qs({ role })}`)
export const fetchPassengers = (q: PassengerQuery = {}) => get<PassengerPage>(`/api/passengers${qs({ ...q })}`)
export const fetchWhy = (groupId: string) => get<Why>(`/api/passengers/${enc(groupId)}/why`)
export const fetchUnresolved = () => get<UnresolvedDest[]>('/api/unresolved')
export const fetchPendingBatch = () => get<Batch | null>('/api/batches/pending')
export const fetchBatches = () => get<BatchRow[]>('/api/batches')
export const fetchBatch = (id: string) => get<Batch>(`/api/batches/${enc(id)}`)
export const approveBatch = (id: string) => post<ApproveResult>(`/api/batches/${enc(id)}/approve`)
export const replan = (body: { fresh?: boolean; weights?: Weights } = {}) => post<{ batch_id: string; cause: string }>('/api/replan', body)
export const fetchRules = () => get<Rules>('/api/rules')
export const putRules = (body: { weights?: Weights; buffers?: Record<string, number> }) => put<Rules>('/api/rules', body)
export const fetchPriorityPolicy = () => get<Record<string, unknown>>('/api/priority-policy')
export const putPriorityPolicy = (policy: Record<string, unknown>, ts_sim?: number) =>
  put<{ status: string; batch_id: string; policy: Record<string, unknown> }>('/api/priority-policy', { policy, ts_sim })
export const fetchNotifier = () => get<NotifierStatus>('/api/notifier')
export const fetchEvents = (q: EventsQuery = {}) => get<EventsPage>(`/api/events${qs({ ...q })}`)
export const overrideGroup = (groupId: string, body: OverrideBody) =>
  post<{ seq: number; batch_id: string | null }>(`/api/groups/${enc(groupId)}/override`, body)
export const verifyGroup = (groupId: string, body: { verification_type: 'CRITICAL_EMERGENCY' | 'COMPANIONS'; verified?: boolean; reason: string; ts_sim?: number }) =>
  post<{ group_id: string; verified: boolean; batch_id: string | null }>(`/api/groups/${enc(groupId)}/verify`, body)

// ------------------------------------------------------------------ field (/api/field)
export const fetchFieldVehicles = () => get<FieldVehicle[]>('/api/field/vehicles')
export const fetchManifest = (vehicleId: string) => get<Manifest>(`/api/field/vehicles/${enc(vehicleId)}/manifest`)
export const boardGroup = (vehicleId: string, body: { allocation_id?: number; group_id?: string }) =>
  post<{ seq: number; allocation_id: number }>(`/api/field/vehicles/${enc(vehicleId)}/board`, body)
export const reportLoad = (vehicleId: string, body: LoadReportBody) =>
  post<{ seq: number; pool_id: string; batch_id: string | null }>(`/api/field/vehicles/${enc(vehicleId)}/load-report`, body)
export const reportVacancy = (vehicleId: string, body: VacancyBody) =>
  post<{ seq: number; batch_id: string | null }>(`/api/field/vehicles/${enc(vehicleId)}/vacancy`, body)

// ------------------------------------------------------------------ phone mock
export const fetchPhoneMessages = (key: string) => get<PhoneThread>(`/api/phone/${enc(key)}/messages`)

// ------------------------------------------------------------------ demo controls (/sim): not part of the product
export const loadScenario = (body: LoadScenarioBody = {}) => post<LoadScenarioResult>('/sim/load-scenario', body)
export const cancelTrain = (body: { vehicle_id?: string; reason?: string } = {}) => post<SimResult>('/sim/cancel-train', body)
export const delayTrain = (body: { vehicle_id: string; delay_min: number }) => post<SimResult>('/sim/delay-train', body)
export const closeRoad = (body: { route_id: string; description?: string }) => post<SimResult>('/sim/close-road', body)
export const injectOvercrowd = (body: { vehicle_id?: string; count?: number } = {}) => post<SimResult>('/sim/inject-overcrowd', body)
export const deployBus = () => post<SimResult>('/sim/deploy-bus')
export const injectVacancies = (body: { vehicle_id?: string; pool_id?: string; seats?: number } = {}) => post<SimResult>('/sim/inject-vacancies', body)
export const fetchSimParams = () => get<SimParams>('/sim/params')
export const putSimParams = (body: Partial<SimParams>) => put<SimParams>('/sim/params', body)
export const setClock = (to_min: number) => post<{ clock: string; clock_min: number }>('/sim/clock', { to_min })
export const departVehicle = (vehicleId: string) => post<DepartResult>(`/sim/depart/${enc(vehicleId)}`)
export const fetchTimeline = () => get<Timeline>('/sim/timeline')
export const timelineNext = () => post<TimelineNextResult>('/sim/timeline/next')
export const timelineReset = () => post<{ next_step: number }>('/sim/timeline/reset')
