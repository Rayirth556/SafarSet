import { API_BASE } from './base'

/** Thin fetch wrapper. Errors from the backend look like `{"detail": {"error", "kind", "fields?"}}`. */
export interface FieldError { field: string; message: string }

export class ApiError extends Error {
  readonly status: number
  /** backend kind (Rejected, StaleBatch, BufferRejected, NoScenario, InvalidRequest, NotFound, ...) or 'Unavailable' when the server cannot be reached */
  readonly kind: string
  readonly fields: FieldError[]
  /** extra explanation from the server, e.g. "blocked by database capacity constraint" on a CapacityRejected */
  readonly detail: string | undefined

  constructor(status: number, kind: string, message: string, fields: FieldError[] = [], detail?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.kind = kind
    this.fields = fields
    this.detail = detail
  }
}

/** GitHub Pages build (VITE_REPLAY=1): there is no server. Screens read the recorded demo (public/replay, one file per step, written by
 *  scripts/record_replay.py), and Next moves to the next recorded step. Live actions are refused with a clear message. */
export const REPLAY = import.meta.env.VITE_REPLAY === '1'
const REPLAY_STEP_KEY = 'safarset-replay-step'
type Snapshot = Record<string, unknown>
type ReplayTimeline = { total: number; steps: { step: number; label: string; at: string; kind: string; type: string }[] }
const replayCache = new Map<number, Promise<Snapshot>>()

function readReplayStep(): number {
  try { return Math.max(0, Number(localStorage.getItem(REPLAY_STEP_KEY)) || 0) } catch { return 0 }
}
let replayStep = readReplayStep()

function setReplayStep(n: number) {
  replayStep = n
  try { localStorage.setItem(REPLAY_STEP_KEY, String(n)) } catch { /* private window: the demo simply starts again on reload */ }
  window.dispatchEvent(new Event('safarset:replay-step'))
}

function loadReplayStep(n: number): Promise<Snapshot> {
  let p = replayCache.get(n)
  if (!p) {
    p = fetch(`${import.meta.env.BASE_URL}replay/steps/${n}.json`).then((r) => {
      if (!r.ok) throw new ApiError(404, 'NotRecorded', `Demo step ${n} is not in the recording.`)
      return r.json() as Promise<Snapshot>
    })
    replayCache.set(n, p)
  }
  return p
}

/** The recorded key: the path, then its query string with the parameters sorted (the form scripts/record_replay.py writes). */
function replayKey(path: string): string {
  const [p, q = ''] = path.split('?')
  const params = new URLSearchParams(q)
  params.sort()
  const s = params.toString()
  return s ? `${p}?${s}` : p
}

async function replayRequest<T>(method: string, path: string): Promise<T> {
  if (method === 'GET') {
    const data = await loadReplayStep(replayStep)
    const k = replayKey(path)
    if (!(k in data)) throw new ApiError(404, 'NotRecorded', 'This screen was not recorded in the demo replay.')
    return data[k] as T
  }
  if (path === '/sim/timeline/next') {
    const current = await loadReplayStep(replayStep)
    const timeline = current['/sim/timeline'] as ReplayTimeline
    if (replayStep >= timeline.total) throw new ApiError(409, 'TimelineDone', 'The scripted demo is finished. Use Reset to play it again.')
    const played = timeline.steps[replayStep]
    setReplayStep(replayStep + 1)
    return { played: { step: played.step, label: played.label, at: played.at, kind: played.kind, type: played.type }, result: {}, next_step: replayStep } as T
  }
  if (path === '/sim/timeline/reset') {
    setReplayStep(0)
    return { next_step: 0 } as T
  }
  throw new ApiError(409, 'ReplayOnly', 'This is the recorded demo: use Next to move through it. Live actions need the server.')
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  if (REPLAY) return replayRequest<T>(method, path)
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: body === undefined ? undefined : { 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'Unavailable', 'Cannot reach the SafarSet server. Is the backend running?')
  }
  const text = await res.text()
  let json: unknown
  try { json = text ? JSON.parse(text) : undefined } catch { json = undefined }
  if (!res.ok) {
    const detail = (json as { detail?: { error?: string; kind?: string; fields?: FieldError[]; detail?: string } } | undefined)?.detail
    if (detail?.error) throw new ApiError(res.status, detail.kind ?? 'Error', detail.error, detail.fields, detail.detail)
    // a dev proxy with no backend behind it answers 5xx with plain text
    if (res.status >= 500) throw new ApiError(res.status, 'Unavailable', 'The SafarSet server is not responding. Is the backend running?')
    throw new ApiError(res.status, 'Error', `Request failed (${res.status})`)
  }
  return json as T
}

export const get = <T>(path: string) => request<T>('GET', path)
export const post = <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {})
export const put = <T>(path: string, body?: unknown) => request<T>('PUT', path, body ?? {})

export function qs(params: Record<string, string | number | boolean | undefined>): string {
  const u = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') u.set(k, String(v))
  const s = u.toString()
  return s ? `?${s}` : ''
}
