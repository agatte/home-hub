import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import settings from '../../src/routes/quiet-atlas/settings/+page.svelte?raw'
import alias from '../../src/routes/settings/+page.svelte?raw'
import rail from '../../src/lib/components/settings/SettingsRail.svelte?raw'
import { MORE_DESTINATIONS, activeQuietAtlasSection, shouldUseQuietAtlasShell, shouldShowGlobalErrorToast, isQuietAtlasReadOnlyPreview } from '../../src/lib/quietAtlas/navigation.js'

describe('Functional redesigned Settings (#461)', () => {
  it('retains all eleven original setting sections in three task groups', () => {
    for (const component of ['Overview','Host','Automation','Dnd','Schedule','Modes','Music','Audio','Network','Learning','GameDay']) expect(settings).toContain('<'+component+'Section />')
    for (const group of ['Systems & access','How HomeHub behaves','Listening & experiences']) expect(settings).toContain("group: '"+group+"'")
    expect(settings).toContain('<SettingsLayout sections={SECTIONS} {activeId} onSelect={select}>')
    expect(rail).toContain('{#each groups as group (group)}')
    expect(alias).toContain('<SettingsWorkspace />')
    expect(settings).not.toContain("withQuietAtlasShell('/settings")
  })
  it('makes both Settings URLs functional with normal failure visibility', () => {
    expect(MORE_DESTINATIONS.find(x=>x.id==='settings')?.href).toBe('/quiet-atlas/settings')
    for (const path of ['/settings','/quiet-atlas/settings']) {
      expect(shouldUseQuietAtlasShell(path,new URLSearchParams())).toBe(true)
      expect(activeQuietAtlasSection(path)).toBe('more')
      expect(isQuietAtlasReadOnlyPreview(path)).toBe(false)
      expect(shouldShowGlobalErrorToast(path,new URLSearchParams())).toBe(true)
    }
  })
  it('preserves URL-owned section navigation and delegates settings writers', () => {
    expect(settings).toContain("const fromUrl = $page.url.searchParams.get('section')")
    expect(settings).toContain("url.searchParams.set('section', id)")
    for (const forbidden of ['apiPost(','apiPut(','setLight(','activateScene(']) expect(settings).not.toContain(forbidden)
    for (const source of [settings,alias,rail]) expect(compile(source,{generate:'dom',css:'external'}).warnings).toEqual([])
  })
})
