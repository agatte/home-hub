import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/svelte'
import { tick } from 'svelte'
import RoomControls from '../../src/lib/components/QuietAtlasRoomControls.svelte'
import { lights } from '../../src/lib/stores/lights.js'
import { connected, deviceStatus } from '../../src/lib/stores/connection.js'
import { lightCommandResults } from '../../src/lib/stores/lightCommandResults.js'
import { setLight } from '../../src/lib/stores/init.js'

vi.mock('../../src/lib/stores/init.js', () => ({ setLight: vi.fn() }))

const fixture = (light_id, on = false, reachable = true) => ({
  light_id, name: 'Fixture ' + light_id, on, reachable,
  bri: 90, hue: 8000, sat: 140, ct: 350, colormode: 'ct',
})

beforeEach(() => {
  vi.clearAllMocks()
  lights.set({ '2': fixture('2'), '3': fixture('3'), '4': fixture('4', true), '5': fixture('5') })
  connected.set(true)
  deviceStatus.set({ hue: true, sonos: true, light_command_results: true })
  lightCommandResults.set({})
})

describe('Kitchen pair power', () => {
  it('sends exactly two separately guarded requests only on deliberate action', async () => {
    render(RoomControls, { room: 'kitchen', id: 'test-kitchen' })
    expect(setLight).not.toHaveBeenCalled()
    expect(screen.getByText('1 of 2 on')).toBeInTheDocument()
    await fireEvent.click(screen.getByRole('button', { name: 'Both on' }))
    expect(setLight.mock.calls).toEqual([['3', { on: true }], ['4', { on: true }]])
    expect(screen.getByText('1 of 2 on')).toBeInTheDocument()
    vi.clearAllMocks()
    await fireEvent.click(screen.getByRole('button', { name: 'Both off' }))
    expect(setLight.mock.calls).toEqual([['3', { on: false }], ['4', { on: false }]])
    expect(screen.getAllByRole('button', { name: /Turn (on|off)/ })).toHaveLength(2)
  })

  it('disables pair while one fixture is pending or unavailable', async () => {
    render(RoomControls, { room: 'kitchen', id: 'test-kitchen' })
    lightCommandResults.set({ '3': { status: 'pending', commandId: 'test-cmd' } })
    await tick()
    expect(screen.getByRole('button', { name: 'Both on' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Both off' })).toBeDisabled()
    lightCommandResults.set({})
    lights.update(prev => ({ ...prev, '4': fixture('4', true, false) }))
    await tick()
    expect(screen.getByRole('button', { name: 'Both on' })).toBeDisabled()
    expect(setLight).not.toHaveBeenCalled()
  })

  it('does not show pair controls in Bedroom', () => {
    render(RoomControls, { room: 'bedroom', id: 'test-bedroom' })
    expect(screen.queryByRole('button', { name: 'Both on' })).not.toBeInTheDocument()
    expect(setLight).not.toHaveBeenCalled()
  })
})
