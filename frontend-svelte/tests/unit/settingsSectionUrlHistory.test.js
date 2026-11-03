import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import settings from '../../src/routes/settings/+page.svelte?raw'

describe('functional Settings URL and browser history synchronization (#461)', () => {
  it('uses URL as section authority when Back/Forward removes or invalidates section', () => {
    expect(settings).toContain("const fromUrl = $page.url.searchParams.get('section')")
    expect(settings).toContain("activeId = fromUrl && SECTIONS.some((s) => s.id === fromUrl) ? fromUrl : 'overview'")
    expect(settings).not.toContain('onMount(() =>')
    expect(settings).toContain("let activeId = 'overview'")
  })

  it('preserves section selection, history entry, all existing destinations and functional controls', () => {
    const sections = [...settings.matchAll(/\{\s*id:\s*'([^']+)',\s*label:/g)].map((m) => m[1])
    expect(sections).toEqual([
      'overview', 'host', 'automation', 'dnd', 'schedule',
      'modes', 'music', 'audio', 'network', 'learning', 'gameday',
    ])
    expect(settings).toContain('activeId = id')
    expect(settings).toContain("url.searchParams.set('section', id)")
    expect(settings).toContain('replaceState: false, keepFocus: true, noScroll: true')
    expect(settings).toContain("{#if activeId === 'overview'}")
    expect(settings).toContain('<SettingsLayout sections={SECTIONS} {activeId} onSelect={select}>')
  })

  it('compiles the existing functional Settings route without Svelte warnings', () => {
    const result = compile(settings, { filename: 'settings/+page.svelte', generate: 'dom', css: 'external' })
    expect(result.warnings).toEqual([])
  })
})
