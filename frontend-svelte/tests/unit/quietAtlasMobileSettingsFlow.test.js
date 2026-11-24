import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import gateway from '../../src/routes/quiet-atlas/settings/+page.svelte?raw'
import rail from '../../src/lib/components/settings/SettingsRail.svelte?raw'
import row from '../../src/lib/components/settings/SettingRow.svelte?raw'
import functional from '../../src/routes/quiet-atlas/settings/+page.svelte?raw'

describe('Quiet Atlas phone-native Settings navigation (#461)', () => {
  it('makes the actual Settings controls the native page rather than an intermediate gateway', () => {
    expect(gateway).toContain('<SettingsLayout sections={SECTIONS} {activeId} onSelect={select}>')
    expect(gateway).not.toContain('withQuietAtlasShell')
    expect(gateway).toContain('settings-workspace')
    expect(rail).toContain('{#each groups as group (group)}')
    expect(gateway).toContain('How HomeHub behaves')
    expect(gateway).toContain('Listening & experiences')
    expect(gateway).toContain('Systems & access')
  })

  it('uses one accessible native section picker for functional mobile settings', () => {
    expect(rail).toContain('<label for="homehub-phone-settings-section">Choose a settings section</label>')
    expect(rail).toContain('<select id="homehub-phone-settings-section" value={activeId} on:change={selectPhoneSection}>')
    expect(rail).toContain('{#each sections as section (section.id)}')
    expect(rail).toContain('<option value={section.id}>{section.label}</option>')
    expect(rail).toContain('if (!(target instanceof HTMLSelectElement)) return')
    expect(rail).toContain('if (sections.some(({ id }) => id === target.value)) onSelect(target.value)')
    expect(rail).toContain('.rail-nav {display:none}')
    expect(rail).toContain('.phone-section-picker {display:flex;')
    expect(rail).toContain('font-size:16px')
    expect(rail).toContain('min-height:52px')
    expect(functional).toContain('url.searchParams.set(\'section\', id)')
    expect(functional).toContain('keepFocus: true')
    expect(functional).toContain('noScroll: true')
  })

  it('stacks real form labels and their existing controls without adding writes', () => {
    expect(row).toContain('.settings-row:not(.stacked) {flex-direction:column;align-items:stretch;gap:10px}')
    expect(row).toContain('.row-control {box-sizing:border-box;width:100%;')
    expect(row).toContain('flex-wrap:wrap;gap:10px}')
    expect(row).toContain('<slot />')
    expect(gateway).not.toMatch(/\b(fetch|apiPost|apiPut|setLight|activateScene|hueWrite)\s*\(/)
    expect(rail).not.toMatch(/\b(fetch|apiPost|apiPut|setLight|activateScene|hueWrite)\s*\(/)
    expect(row).not.toMatch(/\b(fetch|apiPost|apiPut|setLight|activateScene|hueWrite)\s*\(/)
  })

  it('compiles all three affected Svelte components with zero warnings', () => {
    for (const [filename, source] of [
      ['QuietAtlasSettingsGateway.svelte', gateway],
      ['SettingsRail.svelte', rail],
      ['SettingRow.svelte', row],
    ]) {
      const result = compile(source, { filename, generate: 'dom', css: 'external' })
      expect(result.warnings, filename).toEqual([])
    }
  })
})
