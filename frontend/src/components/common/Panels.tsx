import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { cn } from '@/lib/utils'

export function Card({ title, aside, children, className }: { title?: ReactNode; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn('rounded-xl border bg-card p-5', className)}>
      {(title || aside) && (
        <div className="mb-3 flex items-center justify-between gap-3">
          {title && <h2 className="text-lg font-semibold">{title}</h2>}
          {aside}
        </div>
      )}
      {children}
    </section>
  )
}

export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('text-sm font-semibold uppercase tracking-wide text-ink-2', className)}>{children}</div>
}

export function ErrorNote({ error }: { error: Error | null | undefined }) {
  if (!error) return null
  return <p role="alert" className="rounded-md bg-unresolved/10 px-3 py-2 text-sm text-unresolved-ink">{error.message}</p>
}

export function Loading({ what }: { what: string }) {
  return <p className="py-4 text-ink-2">Loading {what}…</p>
}

/** Shown on every surface until a scenario exists. */
export function NoScenario() {
  return (
    <div className="mx-auto mt-16 max-w-xl rounded-xl border bg-card p-8 text-center">
      <h2 className="text-xl font-semibold">No scenario loaded</h2>
      <p className="mt-2 text-ink-2">
        Load one from the demo controls: open <Link to="/sim" className="font-semibold text-navy underline">/sim</Link> and press “Load scenario”.
      </p>
    </div>
  )
}
