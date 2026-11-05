import { useSearchParams } from 'react-router-dom'
import { AppHeader } from '@/components/common/AppHeader'
import { ErrorNote, Loading, NoScenario } from '@/components/common/Panels'
import { Pill } from '@/components/common/StatusChip'
import { useCapacity, useFieldVehicles } from '@/hooks/queries'
import { useAppState } from '@/hooks/useAppState'
import { nameOf, useVehicleIndex } from '@/lib/vehicles'
import { LoadReport } from './LoadReport'
import { Manifest } from './Manifest'
import { VacancyReport } from './VacancyReport'

/** Conductor / TTE view, built for a phone: one column, big touch targets. */
export function FieldPage() {
  const { data: state, error: stateError } = useAppState()
  const { data: vehicles, error } = useFieldVehicles()
  const { data: capacity } = useCapacity('ALLOCATION')
  const names = useVehicleIndex()
  const [params, setParams] = useSearchParams()

  const vehicle = vehicles?.find((v) => v.vehicle_id === params.get('v')) ?? null
  const cap = capacity?.find((v) => v.vehicle_id === vehicle?.vehicle_id)
  const unreserved = cap?.pools.find((p) => p.kind === 'UNRESERVED')

  return (
    <div className="mx-auto min-h-screen max-w-[430px] bg-page sm:border-x sm:border-line">
      <AppHeader subtitle="Field · conductor / TTE" />
      <ErrorNote error={stateError ?? error} />
      {state && !state.loaded && <NoScenario />}
      {state?.loaded && !vehicles && !error && <div className="px-4"><Loading what="vehicles" /></div>}
      {state?.loaded && vehicles && (
        <>
          <section className="px-4 py-4">
            <label className="block text-sm font-semibold uppercase tracking-wide text-ink-2" htmlFor="vehicle">Vehicle</label>
            <select
              id="vehicle"
              className="mt-1 h-14 w-full rounded-lg border-2 border-navy bg-card px-3 text-lg font-semibold"
              value={vehicle?.vehicle_id ?? ''}
              onChange={(e) => setParams(e.target.value ? { v: e.target.value } : {}, { replace: true })}
            >
              <option value="">Choose a vehicle…</option>
              {vehicles.map((v) => (
                <option key={v.vehicle_id} value={v.vehicle_id}>
                  {nameOf(names, v.vehicle_id)} · dep {v.depart}{v.status !== 'SCHEDULED' ? ` · ${v.status.toLowerCase()}` : ''}
                </option>
              ))}
            </select>
            {vehicle && (
              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-base text-ink-2">
                <span>Dep <span className="font-mono text-ink">{vehicle.depart}</span></span>
                {vehicle.delay_min > 0 && <Pill tone="warn">+{vehicle.delay_min} min</Pill>}
                {vehicle.status !== 'SCHEDULED' && <Pill tone="bad" className="uppercase">{vehicle.status}</Pill>}
                {unreserved && <span>Allocatable <span className="font-mono text-ink">{unreserved.formula}</span></span>}
                {vehicle.boarding_note && <span>{vehicle.boarding_note}</span>}
              </div>
            )}
          </section>
          {!vehicle && <p className="px-4 pb-6 text-base text-ink-2">Pick the vehicle you are on to see its passengers and send reports.</p>}
          {vehicle && (
            <div className="divide-y border-t">
              <LoadReport key={vehicle.vehicle_id} vehicle={vehicle} />
              <Manifest vehicleId={vehicle.vehicle_id} />
              <VacancyReport key={`v-${vehicle.vehicle_id}`} vehicle={vehicle} />
            </div>
          )}
        </>
      )}
    </div>
  )
}
