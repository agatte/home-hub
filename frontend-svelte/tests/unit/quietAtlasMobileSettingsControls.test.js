import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import button from '../../src/lib/components/settings/SettingButton.svelte?raw'
import toggle from '../../src/lib/components/settings/SettingToggle.svelte?raw'
import dnd from '../../src/routes/settings/sections/DndSection.svelte?raw'
import schedule from '../../src/routes/settings/sections/ScheduleSection.svelte?raw'

describe('phone-native functional Settings controls (#461)', () => {
  it('enlarges shared action buttons without changing actions or desktop sizing', () => {
    expect(button).toContain('min-height: 36px;')
    expect(button).toContain('@media (max-width: 600px)')
    expect(button).toContain('min-width: 44px;')
    expect(button).toContain('min-height: 48px;')
    expect(button).toContain('font-size: 14px;')
    expect(button).toContain('white-space: normal;')
    expect(button).toContain('disabled={disabled || loading}')
    expect(button).toContain('on:click')
  })

  it('enlarges toggle hitboxes but retains existing explicit disabled / pressed logic', () => {
    expect(toggle).toContain('min-width: 88px;')
    expect(toggle).toContain('min-height: 48px;')
    expect(toggle).toContain('aria-pressed={checked}')
    expect(toggle).toContain('aria-label={label || (checked ?')
    expect(toggle).toContain('if (disabled) return')
    expect(toggle).toContain('onChange(!checked)')
  })

  it('uses a two-column finger-friendly phone-only DND duration picker and full-width action', () => {
    expect(dnd).toContain('grid-template-columns: repeat(2, minmax(0, 1fr));')
    expect(dnd).toContain('.duration-pill { box-sizing: border-box; min-width: 0; min-height: 52px;')
    expect(dnd).toContain('.action-row :global(.settings-btn) { width: 100%; min-height: 52px;')
    expect(dnd).toContain('role="radiogroup" aria-label="DND duration"')
    expect(dnd).toContain('aria-checked={selectedMinutes === opt.minutes}')
    expect(dnd).toContain('await enableDND(selectedMinutes)')
    expect(dnd).toContain('await clearDND()')
    expect(dnd).toContain('catch (e) { error = e instanceof Error ? e.message')
  })

  it('makes schedule tabs, time inputs and ramp steppers usable on a phone', () => {
    expect(schedule).toContain('.day-tabs { box-sizing: border-box; align-self: stretch; width: 100%; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }')
    expect(schedule).toContain('.day-tab { min-width: 0; min-height: 48px;')
    expect(schedule).toContain('.time-input { box-sizing: border-box; width: 100%; min-width: 0; min-height: 48px;')
    expect(schedule).toContain('font-size: 16px;')
    expect(schedule).toContain('grid-template-columns: 52px minmax(0, 1fr) 52px;')
    expect(schedule).toContain('.stepper :global(.settings-btn) { box-sizing: border-box; width: 100%; min-height: 48px;')
    expect(schedule).toContain('label="Morning routine enabled"')
    expect(schedule).toContain('title="Shorten morning ramp"')
    expect(schedule).toContain('title="Lengthen morning ramp"')
    expect(schedule).toContain("try { await apiPut('/api/automation/schedule', scheduleConfig) } catch {}")
    expect(schedule).toContain("try { await apiPut('/api/routines/morning/config', routineConfig) } catch {}")
  })

  it('compiles all four touched Svelte components without warnings', () => {
    for (const [filename, source] of [
      ['SettingButton.svelte', button],
      ['SettingToggle.svelte', toggle],
      ['DndSection.svelte', dnd],
      ['ScheduleSection.svelte', schedule],
    ]) {
      const result = compile(source, { filename, generate: 'dom', css: 'external' })
      expect(result.warnings, filename).toEqual([])
    }
  })
})
