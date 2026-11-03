import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import gateway from '../../src/routes/quiet-atlas/settings/+page.svelte?raw'
import rail from '../../src/lib/components/settings/SettingsRail.svelte?raw'
import row from '../../src/lib/components/settings/SettingRow.svelte?raw'
import functional from '../../src/routes/settings/+page.svelte?raw'

describe('Quiet Atlas phone-native Settings navigation (#461)', () => {
  it('preserves the eleven real settings destinations, with no invented setting', () => {
    const offered = [...gateway.matchAll(/\{\s*id: '([^']+)', label: /g)].map((m) => m[1])
    const actual = [...functional.matchAll(/\{\s*id:\s*'([^']+)',\s*label:/g)].map((m) => m[1])
    expect(offered).toHaveLength(11)
    expect(new Set(offered).size).toBe(11)
    expect(offered.slice().sort()).toEqual(actual.slice().sort())
    expect(gateway).toContain("withQuietAtlasShell('/settings?section=' + item.id)")
    expect(gateway).toContain("withQuietAtlasShell('/settings')")
    expect(gateway).toContain('no live settings or device state')
  })

  it('uses progressively disclosed mobile categories while retaining the desktop directory', () => {
    expect(gateway).toContain("let expandedGroup = 'behavior'")
    expect(gateway).toContain('aria-controls={\'settings-links-\' + group.id}')
    expect(gateway).toContain('aria-expanded={expandedGroup === group.id}')
    expect(gateway).toContain('on:click={() => expandedGroup = expandedGroup === group.id ? null : group.id}')
    expect(gateway).toContain("id={'settings-links-' + group.id}")
    expect(gateway).toContain('class:mobile-collapsed={expandedGroup !== group.id}')
    expect(gateway).toContain('.section-links.mobile-collapsed {display:none}')
    expect(gateway).toContain('.mobile-group-toggle {display:flex;')
    expect(gateway).toContain('.mobile-group-toggle:focus-visible')
    expect(gateway).toContain('.setting-link {box-sizing:border-box;min-height:64px;')
    expect(gateway).toContain('.all-settings {box-sizing:border-box;display:flex;')
    expect(gateway).toContain('href="/quiet-atlas/home"')
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
