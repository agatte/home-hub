import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { compile } from 'svelte/compiler'
import { render, fireEvent, cleanup } from '@testing-library/svelte'
import { tick } from 'svelte'
import home from '../../src/routes/quiet-atlas/home/+page.svelte?raw'
import panel from '../../src/lib/components/QuietAtlasHomeModeControls.svelte?raw'
import ModeControls from '../../src/lib/components/QuietAtlasHomeModeControls.svelte'
import classic from '../../src/routes/classic/+page.svelte?raw'
import storeActions from '../../src/lib/stores/init.js?raw'
import { connected } from '../../src/lib/stores/connection.js'
import { automation, initialAutomationState } from '../../src/lib/stores/automation.js'
import { setManualMode } from '../../src/lib/stores/init.js'

vi.mock('../../src/lib/stores/init.js', () => ({ setManualMode: vi.fn(async () => 'acknowledged') }))
const report = (house_state = 'home', mode = 'working', override_user_owned = false) =>
  automation.set({ ...initialAutomationState, house_state, mode, override_user_owned })
beforeEach(() => { vi.clearAllMocks(); connected.set(true); report() })
afterEach(() => { cleanup(); connected.set(false); automation.set(initialAutomationState) })

describe('#461 direct Home mode tiles', () => {
  it('preserves the established authenticated writer and all modes', () => {
    expect(home).toContain('<QuietAtlasHomeModeControls />')
    expect(classic).toContain('<ModeCardDeck />')
    expect(panel).toContain('setManualMode(mode)')
    expect(storeActions).toContain("apiPost('/api/automation/override', { mode })")
    expect(panel).not.toContain('setLight(')
    expect(panel).not.toContain('light_command')
    expect(panel).not.toContain('<select')
    expect(panel).not.toContain('<details')
    expect(compile(panel, { filename:'QuietAtlasHomeModeControls.svelte',generate:'dom',css:'external' }).warnings).toEqual([])
  })
  it('gives each activity its existing semantic palette without implying selection', () => {
    const view = render(ModeControls)
    for (const [label,palette] of [['Relax','calm'],['Working','focus'],['Watching','cinema'],['Gaming','play'],['Cooking','warm'],['Party','social'],['Sleep','sleep'],['Return to Auto','neutral']]) {
      const button = view.getByRole('button',{name:label})
      expect(button.getAttribute('data-palette')).toBe(palette)
      expect(button.getAttribute('aria-pressed')).toBe(String(label === 'Return to Auto'))
    }
    expect(setManualMode).not.toHaveBeenCalled()
  })
  it('offers eight direct buttons, sends no action on mount and never marks an acknowledgement as a reported mode', async () => {
    const view = render(ModeControls)
    for (const label of ['Relax','Working','Watching','Gaming','Cooking','Party','Sleep','Return to Auto']) expect(view.getByRole('button',{name:label})).toBeTruthy()
    expect(setManualMode).not.toHaveBeenCalled()
    expect(view.getByRole('button',{name:'Return to Auto'}).getAttribute('aria-pressed')).toBe('true')
    await fireEvent.click(view.getByRole('button',{name:'Gaming'}))
    expect(setManualMode).toHaveBeenCalledOnce()
    expect(setManualMode).toHaveBeenCalledWith('gaming')
    expect(view.getByRole('button',{name:'Gaming'}).getAttribute('aria-pressed')).toBe('false')
    report('home','gaming',true); await tick()
    expect(view.getByRole('button',{name:'Gaming'}).getAttribute('aria-pressed')).toBe('true')
  })
  it.each(['away','sleeping'])('requires a separate explicit confirmation from %s; double tap is not enough', async state => {
    report(state)
    const view=render(ModeControls)
    const auto=view.getByRole('button',{name:'Return to Auto'})
    await fireEvent.click(auto); await fireEvent.click(auto)
    expect(setManualMode).not.toHaveBeenCalled()
    await fireEvent.click(view.getByRole('button',{name:'Confirm Auto'}))
    expect(setManualMode).toHaveBeenCalledOnce()
    expect(setManualMode).toHaveBeenCalledWith('auto')
  })
  it('requires deliberate Sleep confirmation and cancels on disconnect or house-state change', async () => {
    const view=render(ModeControls)
    await fireEvent.click(view.getByRole('button',{name:'Sleep'}))
    expect(setManualMode).not.toHaveBeenCalled()
    await fireEvent.click(view.getByRole('button',{name:'Cancel'}))
    expect(view.queryByRole('button',{name:'Confirm Sleep'})).toBeNull()
    await fireEvent.click(view.getByRole('button',{name:'Sleep'}))
    report('away'); await tick()
    expect(view.queryByRole('button',{name:'Confirm Sleep'})).toBeNull()
    await fireEvent.click(view.getByRole('button',{name:'Gaming'}))
    connected.set(false); await tick()
    expect(view.queryByRole('button',{name:'Confirm Gaming'})).toBeNull()
    expect(view.getByRole('button',{name:'Gaming'}).hasAttribute('disabled')).toBe(true)
    expect(setManualMode).not.toHaveBeenCalled()
  })
})
