import { createContext, useContext } from 'react'

/** connecting: no socket yet. live: snapshot received. resyncing: a sequence gap was found, waiting for a snapshot. reconnecting: socket lost. */
export type LiveStatus = 'connecting' | 'live' | 'resyncing' | 'reconnecting'

/** One wording for the connection state on every screen. `live` is the colour of the dot as well. */
export const STATUS_LABEL: Record<LiveStatus, { text: string; tone: 'ok' | 'warn' | 'bad' }> = {
  live: { text: 'Live', tone: 'ok' },
  connecting: { text: 'Connecting…', tone: 'warn' },
  resyncing: { text: 'Resyncing…', tone: 'warn' },
  reconnecting: { text: 'Reconnecting…', tone: 'bad' },
}

interface LiveValue { status: LiveStatus; lastSeq: number | null }
export const LiveContext = createContext<LiveValue>({ status: 'connecting', lastSeq: null })
export const useLive = () => useContext(LiveContext)
