import { useSearchParams } from 'react-router-dom'
import { AppHeader } from '@/components/common/AppHeader'
import { ErrorNote, Loading, NoScenario } from '@/components/common/Panels'
import { Pill } from '@/components/common/StatusChip'
import { useCapacity, useFieldVehicles } from '@/hooks/queries'
import { useAppState } from '@/hooks/useAppState'
import { nameOf, useVehicleIndex } from '@/lib/vehicles'
import { LoadReport } from './LoadReport'
import { Manifest } from './Manifest'
import { parseRole, roleOfMode, ROLE_LABEL, vehiclesFor, type FieldRole } from './roles'
import { VacancyReport } from './VacancyReport'

const label = 'block text-sm font-semibold uppercase tracking-wide text-ink-2'
const select = 'mt-1 h-14 w-full rounded-lg border-2 border-navy bg-card px-3 text-lg font-semibold disabled:border-line disabled:text-ink-2'

/**
 * Field view, built for a phone: one column, big touch targets. The person picks their role first (a conductor works a bus, a TTE works a
 * train), then only that role's vehicles are listed, and only that role's reports are shown. `?v=` alone still works: it opens the role that
 * works that vehicle.
 */
export function FieldPage() {
  const { data: state, error: stateError } = useAppState()
  const { data: vehicles, error } = useFieldVehicles()
  const { data: capacity } = useCapacity('ALLOCATION')
  const names = useVehicleIndex()
  const [params, setParams] = useSearchParams()

  const named = vehicles?.find((v) => v.vehicle_id === params.get('v')) ?? null
  const role: FieldRole | null = parseRole(params.get('role')) ?? (named ? roleOfMode(named.mode) : null)
  const options = vehiclesFor(role, vehicles ?? [])
  const vehicle = options.find((v) => v.vehicle_id === named?.vehicle_id) ?? null     // a vehicle the role does not work is not shown
  const cap = capacity?.find((v) => v.vehicle_id === vehicle?.vehicle_id)
  const unreserved = cap?.pools.find((p) => p.kind === 'UNRESERVED')

  const pickRole = (r: string) => setParams(r ? { role: r } : {}, { replace: true })           // a new role starts with no vehicle
  const pickVehicle = (id: string) => setParams(id ? { role: role!, v: id } : { role: role! }, { replace: true })

  return (
    <div className="mx-auto min-h-screen max-w-[430px] bg-page sm:border-x sm:border-line">
      <AppHeader subtitle="Field · conductor / TTE" />
      <ErrorNote error={stateError ?? error} />
      {state && !state.loaded && <NoScenario />}
      {state?.loaded && !vehicles && !error && <div className="px-4"><Loading what="vehicles" /></div>}
      {state?.loaded && vehicles && (
        <>
          <section className="space-y-3 px-4 py-4">
            <div>
              <label className={label} htmlFor="role">I am a</label>
              <select id="role" className={select} value={role ?? ''} onChange={(e) => pickRole(e.target.value)}>
                <option value="">Choose your role…</option>
                {(Object.keys(ROLE_LABEL) as FieldRole[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
              </select>
            </div>
            <div>
              <label className={label} htmlFor="vehicle">{role === 'tte' ? 'Train' : 'Bus'}</label>
              <select id="vehicle" className={select} disabled={!role} value={vehicle?.vehicle_id ?? ''} onChange={(e) => pickVehicle(e.target.value)}>
                <option value="">{role ? `Choose a ${role === 'tte' ? 'train' : 'bus'}…` : 'Choose your role first'}</option>
                {options.map((v) => (
                  <option key={v.vehicle_id} value={v.vehicle_id}>
                    {nameOf(names, v.vehicle_id)} · dep {v.depart}{v.status !== 'SCHEDULED' ? ` · ${v.status.toLowerCase()}` : ''}
                  </option>
                ))}
              </select>
            </div>
            {vehicle && (
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-base text-ink-2">
                <span>Dep <span className="font-mono text-ink">{vehicle.depart}</span></span>
                {vehicle.delay_min > 0 && <Pill tone="warn">+{vehicle.delay_min} min</Pill>}
                {vehicle.status !== 'SCHEDULED' && <Pill tone="bad" className="uppercase">{vehicle.status}</Pill>}
                {unreserved && <span>Allocatable <span className="font-mono text-ink">{unreserved.formula}</span></span>}
                {vehicle.boarding_note && <span>{vehicle.boarding_note}</span>}
              </div>
            )}
          </section>
          {!role && <p className="px-4 pb-6 text-base text-ink-2">Choose your role to see the vehicles you work.</p>}
          {role && !vehicle && <p className="px-4 pb-6 text-base text-ink-2">Pick the {role === 'tte' ? 'train' : 'bus'} you are on to see its passengers and send reports.</p>}
          {vehicle && role === 'conductor' && (
            <div className="divide-y border-t">
              <LoadReport key={vehicle.vehicle_id} vehicle={vehicle} />
              <Manifest vehicleId={vehicle.vehicle_id} />
            </div>
          )}
          {vehicle && role === 'tte' && (
            <div className="divide-y border-t">
              <VacancyReport key={`v-${vehicle.vehicle_id}`} vehicle={vehicle} />
              <LoadReport key={vehicle.vehicle_id} vehicle={vehicle} />
              <Manifest vehicleId={vehicle.vehicle_id} />
            </div>
          )}
        </>
      )}
    </div>
  )
}
