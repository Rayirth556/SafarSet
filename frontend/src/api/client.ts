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

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
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
