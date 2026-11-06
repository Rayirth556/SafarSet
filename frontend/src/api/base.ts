/** Where the backend lives. Empty in development: Vite proxies /api, /sim and /ws to the local backend.
 *  On Vercel, VITE_API_BASE is the Render service URL (for example https://safarset-api.onrender.com). */
export const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')

/** WebSocket URL for a backend path, on the same host as the API. */
export function wsUrlFor(path: string): string {
  const url = new URL(path, API_BASE || location.origin)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}
