# SafarSet frontend

Vite + React + TypeScript + Tailwind v4 + shadcn/ui + TanStack Query. Start everything with `python scripts/dev.py` from the repo root.

- `src/api/` typed client for `docs/api.md` (`types.ts`, `endpoints.ts`, `client.ts`)
- `src/live/` the `/ws` stream: `router.ts` (sequence-gap detection, pure and tested), `invalidation.ts` (hint topic to query keys), `LiveProvider.tsx`
- Server state lives only in the TanStack cache; the WebSocket keeps it fresh. Nothing in the UI is hard-coded data.
- Tests: `npm test`. Type check: `npx tsc -b`. Design reference: `design/`.
