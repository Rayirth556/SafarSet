import { createContext, useContext } from 'react'

/** connecting: no socket yet. live: snapshot received. resyncing: a sequence gap was found, waiting for a snapshot. reconnecting: socket lost. */
export type LiveStatus = 'connecting' | 'live' | 'resyncing' | 'reconnecting'

interface LiveValue { status: LiveStatus; lastSeq: number | null }
export const LiveContext = createContext<LiveValue>({ status: 'connecting', lastSeq: null })
export const useLive = () => useContext(LiveContext)
