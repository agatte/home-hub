import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import button from '../../src/lib/components/settings/SettingButton.svelte?raw'
import automation from '../../src/routes/settings/sections/AutomationSection.svelte?raw'
import overview from '../../src/routes/settings/sections/OverviewSection.svelte?raw'

describe('phone-native Automation and Overview settings (#461)', () => {
  it('preserves shared settings button action and introduces an optional accessible label', () => {
    expect(button).toContain('export let ariaLabel = undefined')
    expect(button).toContain('aria-label={ariaLabel}')
    expect(button).toContain('disabled={disabled || loading}')
    expect(button).toContain('on:click')
    expect(button).toContain('min-height: 48px;')
  })

  it('keeps automation read/write contracts and source qualifiers intact', () => {
    expect(automation).toContain("await apiPut('/api/automation/config', autoConfig)")
    expect(automation).toContain("await apiPost('/api/camera/enable', { enabled })")
    expect(automation).toContain("personality = await apiPost('/api/personality/settings', payload)")
    expect(automation).toContain("calibrateResult = await apiPost('/api/camera/calibrate', {})")
    expect(automation).toContain("if (p.zone === 'couch')")
    expect(automation).toContain("if (p.at_desk_fresh)")
    expect(automation).toContain('class:stale={!info.fresh}')
    expect(automation).toContain('ariaLabel="Decrease manual override timeout"')
    expect(automation).toContain('ariaLabel="Increase manual override timeout"')
  })

  it('offers thumb-sized automation adjustments and readable source evidence on narrow screens', () => {
    expect(automation).toContain('@media (max-width: 600px)')
    expect(automation).toContain('grid-template-columns: 52px minmax(0, 1fr) 52px;')
    expect(automation).toContain('.stepper :global(.settings-btn) { box-sizing: border-box; width: 100%; min-height: 52px;')
    expect(automation).toContain('.source-list { box-sizing: border-box; justify-content: flex-start; width: 100%;')
    expect(automation).toContain('.source-chip { display: inline-flex; align-items: center; min-height: 32px;')
    expect(automation).toContain('.value-chip { box-sizing: border-box; max-width: 100%; flex-wrap: wrap;')
    expect(automation).toContain('overflow-wrap: anywhere;')
  })

  it('wraps diagnostic build hashes and preserves explicit status and test action semantics', () => {
    expect(overview).toContain("await apiGet('/health')")
    expect(overview).toContain("await apiPost('/api/sonos/tts'")
    expect(overview).toContain("await apiPost('/api/notification/test', { kind: 'suggestion' })")
    expect(overview).toContain('class:ok={$connected}')
    expect(overview).toContain('class:ok={$deviceStatus.hue}')
    expect(overview).toContain('health.build_id')
    expect(overview).toContain('@media (max-width: 600px)')
    expect(overview).toContain('.status-pill { box-sizing: border-box; min-height: 32px;')
    expect(overview).toContain('.value-pill.mono { font-size: 12px; overflow-wrap: anywhere; word-break: break-all; }')
    expect(overview).toContain('.feedback { margin: 10px 0 0; font-size: 13px;')
  })

  it('compiles the three touched Svelte components without warnings', () => {
    for (const [filename, source] of [
      ['SettingButton.svelte', button],
      ['AutomationSection.svelte', automation],
      ['OverviewSection.svelte', overview],
    ]) {
      const result = compile(source, { filename, generate: 'dom', css: 'external' })
      expect(result.warnings, filename).toEqual([])
    }
  })
})
