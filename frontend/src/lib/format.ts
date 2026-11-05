/** Minutes of day -> "HH:MM". */
export function hhmm(min: number | null | undefined): string {
  if (min == null) return '--:--'
  const m = ((min % 1440) + 1440) % 1440
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
}

/** "SIM3141893" -> "…1893": the mockups show only the tail of a PNR. */
export function pnrTail(pnr: string | null | undefined, n = 4): string | null {
  return pnr ? `…${pnr.slice(-n)}` : null
}

export const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`
