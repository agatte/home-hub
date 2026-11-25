import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import gateway from '../../src/routes/quiet-atlas/settings/+page.svelte?raw'
import rail from '../../src/lib/components/settings/SettingsRail.svelte?raw'
import row from '../../src/lib/components/settings/SettingRow.svelte?raw'
import functional from '../../src/routes/quiet-atlas/settings/+page.svelte?raw'

describe('Quiet Atlas phone-native Settings navigation (#461)', () => {
  it('makes the actual Settings controls the native page rather than an intermediate gateway', () => {
    expect(gateway).toContain('<SettingsLayout sections={SECTIONS} {activeId} {indexView} {indexHref} onSelect={select}>')
    expect(gateway).not.toContain('withQuietAtlasShell')
    expect(gateway).toContain('settings-workspace')
    expect(rail).toContain('{#each groups as group (group)}')
    expect(gateway).toContain('How HomeHub behaves')
    expect(gateway).toContain('Listening & experiences')
    expect(gateway).toContain('Systems & access')
  })

  it('uses a grouped index and persistent direct parent link for mobile detail', () => {
    expect(rail).toContain('class:index-view={indexView}')
    expect(rail).toContain('href={indexHref} data-sveltekit-replacestate')
    expect(rail).toContain('aria-label="Back to Settings sections"')
    expect(rail).toContain('if (indexView || id !== activeId) onSelect(id)')
    expect(rail).toContain("aria-current={!indexView && activeId === section.id ? 'page' : undefined}")
    expect(rail).toContain('.rail-nav{display:none;}')
    expect(rail).toContain('.index-view .rail-nav{display:grid;')
    expect(rail).toContain('position:sticky;top:0')
    expect(rail).toContain('min-height:56px')
    expect(rail).not.toContain('<select')
    expect(functional).toContain("url.searchParams.set('section', id)")
    expect(functional).toContain("parent.searchParams.delete('section')")
    expect(functional).toContain('indexView = !valid')
    expect(functional).not.toContain('noScroll: true')
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
