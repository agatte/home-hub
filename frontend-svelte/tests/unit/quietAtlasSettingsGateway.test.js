import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import gateway from '../../src/routes/quiet-atlas/settings/+page.svelte?raw'
import legacySettings from '../../src/routes/settings/+page.svelte?raw'
import {
  MORE_DESTINATIONS, activeQuietAtlasSection, shouldUseQuietAtlasShell,
  shouldShowGlobalErrorToast, withQuietAtlasShell,
} from '../../src/lib/quietAtlas/navigation.js'

describe('Quiet Atlas opt-in Settings directory', () => {
  it('matches every supported functional Settings section without inventing one', () => {
    const ids = [...gateway.matchAll(/\{\s*id: '([^']+)', label: /g)].map((m) => m[1])
    const actual = [...legacySettings.matchAll(/\{\s*id:\s*'([^']+)',\s*label:/g)].map((m) => m[1])
    expect(ids).toHaveLength(11)
    expect(new Set(ids).size).toBe(ids.length)
    expect([...ids].sort()).toEqual([...actual].sort())
    expect(gateway).toContain("withQuietAtlasShell('/settings?section=' + item.id)")
    expect(withQuietAtlasShell('/settings?section=dnd')).toBe('/settings?section=dnd&shell=quiet-atlas')
  })

  it('routes More to the review, and keeps legacy Settings operational and visible', () => {
    const item = MORE_DESTINATIONS.find(({ id }) => id === 'settings')
    expect(item).toMatchObject({ href: '/quiet-atlas/settings', shell: false })
    expect(shouldUseQuietAtlasShell('/quiet-atlas/settings', new URLSearchParams())).toBe(true)
    expect(activeQuietAtlasSection('/quiet-atlas/settings')).toBe('more')
    expect(activeQuietAtlasSection('/quiet-atlas/home')).toBe('home')
    expect(shouldShowGlobalErrorToast('/settings', new URLSearchParams('shell=quiet-atlas'))).toBe(true)
    expect(gateway).toContain("withQuietAtlasShell('/settings')")
    expect(gateway).toContain('href="/quiet-atlas/home"')
    expect(gateway).toContain('Each destination opens an existing Settings section')
  })

  it('stays a navigation-only and accessible design archetype, not a status or settings writer', () => {
    expect(gateway).toContain('navigation-only Settings directory')
    expect(gateway).toContain('aria-label={group.title}')
    expect(gateway).toContain('aria-labelledby={\'settings-\' + group.id}')
    expect(gateway).toContain('no live settings or device state')
    expect(gateway).not.toMatch(/\b(fetch|apiGet|apiPost|apiPut|goto|setLight|activateScene|hueWrite)\s*\(/)
    const result = compile(gateway, { filename: 'QuietAtlasSettingsGateway.svelte', generate: 'dom', css: 'external' })
    expect(result.warnings).toEqual([])
  })
})
