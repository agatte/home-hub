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
    expect(vi.mocked(setLight).mock.calls).toEqual([['3', { on: true }], ['4', { on: true }]])
    expect(screen.getByText('1 of 2 on')).toBeInTheDocument()
    vi.clearAllMocks()
    await fireEvent.click(screen.getByRole('button', { name: 'Both off' }))
    expect(vi.mocked(setLight).mock.calls).toEqual([['3', { on: false }], ['4', { on: false }]])
    vi.clearAllMocks()
    await fireEvent.click(screen.getByRole('button', { name: 'Individually' }))
    expect(screen.getAllByRole('button', { name: /Turn (on|off)/ })).toHaveLength(2)
    expect(setLight).not.toHaveBeenCalled()
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

describe('Kitchen linked precision controls', () => {
  function bothOn() {
    lights.set({ '2': fixture('2'), '3': fixture('3', true),
      '4': { ...fixture('4', true), bri: 160 }, '5': fixture('5') })
  }

  it('starts without writes and labels the primary reference even if brightness differs', async () => {
    bothOn()
    render(RoomControls, { room: 'kitchen', id: 'linked-kitchen' })
    expect(screen.getByRole('button', { name: 'Together' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText(/Kitchen back \(L4\) may differ/)).toBeInTheDocument()
    expect(setLight).not.toHaveBeenCalled()
    await fireEvent.keyDown(screen.getByRole('button', { name: /Kitchen · front reference/ }), { key: 'ArrowRight' })
    expect(vi.mocked(setLight).mock.calls).toEqual([
      ['3', { bri: 103 }, { optimistic: false }], ['4', { bri: 103 }, { optimistic: false }],
    ])
  })

  it('sends linked color and temperature only to the exact kitchen pair', async () => {
    bothOn()
    render(RoomControls, { room: 'kitchen', id: 'linked-color' })
    await fireEvent.click(screen.getByRole('button', { name: 'Change color' }))
    await fireEvent.click(screen.getByTitle('Blue'))
    expect(vi.mocked(setLight).mock.calls).toEqual([
      ['3', { hue: 46920, sat: 254 }, { optimistic: false }],
      ['4', { hue: 46920, sat: 254 }, { optimistic: false }],
    ])
    vi.clearAllMocks()
    await fireEvent.click(screen.getByRole('button', { name: 'Change color' }))
    await fireEvent.click(screen.getByRole('button', { name: 'Temp' }))
    const temp = document.querySelector('.chip-preset-dot')
    expect(temp).toBeTruthy()
    await fireEvent.click(temp)
    const calls = vi.mocked(setLight).mock.calls
    expect(calls).toHaveLength(2)
    expect(calls.map(c => c[0])).toEqual(['3', '4'])
    expect(calls[0][1]).toEqual({ ct: expect.any(Number) })
    expect(calls[1][1]).toEqual(calls[0][1])
  })

  it('switches to independent cards without dispatch and targets only the selected fixture', async () => {
    bothOn()
    render(RoomControls, { room: 'kitchen', id: 'individual-kitchen' })
    await fireEvent.click(screen.getByRole('button', { name: 'Individually' }))
    expect(setLight).not.toHaveBeenCalled()
    await fireEvent.keyDown(screen.getByRole('button', { name: /Fixture 4 \(/ }), { key: 'ArrowLeft' })
    expect(vi.mocked(setLight).mock.calls).toEqual([['4', { bri: 147 }, { optimistic: false }]])
    vi.clearAllMocks()
    await fireEvent.click(screen.getByRole('button', { name: 'Together' }))
    expect(setLight).not.toHaveBeenCalled()
  })

  it('withholds linked precision when mixed power, missing, unreachable or pending', async () => {
    render(RoomControls, { room: 'kitchen', id: 'unsafe-kitchen' })
    expect(screen.queryByRole('button', { name: /Kitchen · front reference/ })).not.toBeInTheDocument()
    bothOn()
    await tick()
    lightCommandResults.set({ '4': { status: 'pending', commandId: 'pending' } })
    await tick()
    expect(screen.getByRole('button', { name: /Kitchen · front reference/ })).toBeDisabled()
    lightCommandResults.set({})
    lights.update(prev => ({ ...prev, '4': fixture('4', true, false) }))
    await tick()
    expect(screen.queryByRole('button', { name: /Kitchen · front reference/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Both on' })).toBeDisabled()
    lights.update(({ '4': removed, ...prev }) => prev)
    await tick()
    expect(screen.getByRole('button', { name: 'Both off' })).toBeDisabled()
    await fireEvent.click(screen.getByRole('button', { name: 'Individually' }))
    expect(screen.getByRole('button', { name: /Fixture 3 \(/ })).toBeEnabled()
    expect(setLight).not.toHaveBeenCalled()
  })

  it('retains independent command outcomes when a partial response leaves mixed power', async () => {
    bothOn()
    render(RoomControls, { room: 'kitchen', id: 'partial-kitchen' })
    lightCommandResults.set({ '3': { status: 'acknowledged' }, '4': { status: 'denied' } })
    await tick()
    expect(screen.getByText(/Light 3:.*Bridge acknowledged/)).toBeInTheDocument()
    expect(screen.getByText(/Light 4:.*Change blocked/)).toBeInTheDocument()
    lights.update(prev => ({ ...prev, '3': fixture('3', false) }))
    await tick()
    expect(screen.getByText(/L3: Bridge acknowledged/)).toBeInTheDocument()
    expect(screen.getByText(/L4: Blocked by lighting ownership/)).toBeInTheDocument()
    expect(setLight).not.toHaveBeenCalled()
  })
})
