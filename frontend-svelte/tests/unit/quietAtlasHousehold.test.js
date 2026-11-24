import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import home from '../../src/routes/quiet-atlas/home/+page.svelte?raw'
import household from '../../src/routes/quiet-atlas/household/+page.svelte?raw'
import { MORE_DESTINATIONS, activeQuietAtlasSection, shouldUseQuietAtlasShell, isQuietAtlasReadOnlyPreview, shouldShowGlobalErrorToast } from '../../src/lib/quietAtlas/navigation.js'
import { rootRuntimeTargets } from '../../src/lib/quietAtlas/runtimeRoutePolicy431.js'

describe('Functional household migration (#461)', () => {
  it('sends both Home entries and More to the same functional route, not Classic', () => {
    expect(home.split('href="/quiet-atlas/household"').length - 1).toBe(2)
    expect(home).not.toContain('href="/classic"')
    expect(home).not.toContain('href="/quiet-atlas"')
    expect(MORE_DESTINATIONS.find(x => x.id === 'apartment')?.href).toBe('/quiet-atlas/household')
    expect(activeQuietAtlasSection('/quiet-atlas/household')).toBe('more')
    expect(shouldUseQuietAtlasShell('/quiet-atlas/household',new URLSearchParams())).toBe(true)
    expect(isQuietAtlasReadOnlyPreview('/quiet-atlas/household')).toBe(false)
    expect(shouldShowGlobalErrorToast('/quiet-atlas/household',new URLSearchParams())).toBe(true)
    expect(rootRuntimeTargets('/quiet-atlas/household')).toEqual({general:true,gameday:false})
  })
  it('preserves existing household widgets and uses the current guarded Control destination', () => {
    for (const component of ['PlantWidget','BarWidget','GuestWifiWidget','RoutineCard','AmbientSoundWidget','PiholeCard','ApartmentViz']) expect(household).toContain('<'+component+' />')
    expect(household).toContain('href="/quiet-atlas/control"')
    expect(household).toContain('href={CONTROL_SCENES_HREF}')
    expect(household).toContain('$connected && $deviceStatus.hue')
    expect(household).toContain('Temporary compatibility tools')
    expect(household.split('href="/classic"').length - 1).toBe(1)
    for (const forbidden of ['apiPost(','apiPut(','fetch(','setLight(','<ApartmentWidget','<LightGrid','<SceneBrowser']) expect(household).not.toContain(forbidden)
  })
  it('compiles the real route with no Svelte warnings', () => {
    expect(compile(household,{generate:'dom',css:'external'}).warnings).toEqual([])
  })
})
