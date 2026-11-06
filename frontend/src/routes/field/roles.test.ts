import { describe, expect, it } from 'vitest'
import type { FieldVehicle } from '@/api/types'
import { parseRole, roleOfMode, vehiclesFor } from './roles'

const veh = (vehicle_id: string, mode: string): FieldVehicle =>
  ({ vehicle_id, mode, label: '', name: null, train_no: null, route_id: null, status: 'SCHEDULED', depart: '14:40', delay_min: 0, boarding_note: null, pools: [] })
const all = [veh('BUS-1', 'BUS'), veh('TRAIN-1', 'TRAIN'), veh('BUS-2', 'BUS')]

describe('vehiclesFor', () => {
  it('a conductor sees buses only', () => expect(vehiclesFor('conductor', all).map((v) => v.vehicle_id)).toEqual(['BUS-1', 'BUS-2']))
  it('a TTE sees trains only', () => expect(vehiclesFor('tte', all).map((v) => v.vehicle_id)).toEqual(['TRAIN-1']))
  it('no role, no vehicles', () => expect(vehiclesFor(null, all)).toEqual([]))
})

describe('roles from the URL and from a vehicle', () => {
  it('accepts only the two roles', () => {
    expect(parseRole('conductor')).toBe('conductor'); expect(parseRole('tte')).toBe('tte')
    expect(parseRole('driver')).toBeNull(); expect(parseRole(null)).toBeNull()
  })
  it('a bus belongs to the conductor and a train to the TTE', () => {
    expect(roleOfMode('BUS')).toBe('conductor'); expect(roleOfMode('TRAIN')).toBe('tte'); expect(roleOfMode('FERRY')).toBeNull()
  })
})
