import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import root from '../../src/routes/+page.svelte?raw'
import classic from '../../src/routes/classic/+page.svelte?raw'
import home from '../../src/routes/quiet-atlas/home/+page.svelte?raw'
import reveal from '../../src/lib/components/QuietAtlasHomeLightingReveal.svelte?raw'
import controls from '../../src/lib/components/QuietAtlasRoomControls.svelte?raw'
import cardSource from '../../src/lib/components/LightCard.svelte?raw'
import initSource from '../../src/lib/stores/init.js?raw'
import shell from '../../src/lib/components/QuietAtlasShell.svelte?raw'
import { MORE_DESTINATIONS, activeQuietAtlasSection, shouldUseQuietAtlasShell, shouldShowGlobalErrorToast } from '../../src/lib/quietAtlas/navigation.js'

describe('default redesigned Home and existing working lighting cutover (#461)', () => {
  it('makes the designed Home the root while preserving an exact classic fallback', () => {
    expect(root).toContain("import RedesignedHome from './quiet-atlas/home/+page.svelte'")
    expect(root).toContain('<RedesignedHome />')
    expect(classic).toContain('<ApartmentWidget />')
    expect(classic).toContain('id="apartment-controls"')
    expect(shouldUseQuietAtlasShell('/', new URLSearchParams())).toBe(true)
    expect(shouldUseQuietAtlasShell('/classic', new URLSearchParams('shell=quiet-atlas'))).toBe(false)
    expect(activeQuietAtlasSection('/')).toBe('home')
    expect(MORE_DESTINATIONS.find(x => x.id === 'apartment')?.href).toBe('/classic')
    expect(shell).toContain("{ id: 'home', label: 'Home', href: '/'")
    expect(shouldShowGlobalErrorToast('/', new URLSearchParams())).toBe(true)
  })

  it('uses existing LightCard/WS controls for each actual fixture, without paired fanout', () => {
    expect(reveal).toContain('<QuietAtlasRoomControls room={group.id}')
    expect(reveal).not.toContain('Preview glow')
    expect(reveal).not.toContain('Preview on')
    expect(controls).toContain("import LightCard from './LightCard.svelte'")
    for (const mapping of ["living: ['1']", "bedroom: ['2', '5']", "kitchen: ['3', '4']", "plant: ['6']"]) {
      expect(controls).toContain(mapping)
    }
    expect(controls).toContain('<LightCard light={$lights[lightId]} optimisticStore={false} />')
    expect(controls).not.toContain('linkedIds=')
    expect(controls).not.toContain('<LightGrid')
    expect(controls).not.toContain('fetch(')
    expect(controls).not.toContain('apiPut(')
    expect(controls).toContain('!$connected')
    expect(controls).toContain('$lights[lightId].reachable === true')
    expect(controls).toContain('controls unavailable')
    // No global optimistic patch in the new Home: a WS send is not an ACK.
    expect(cardSource).toContain('export let optimisticStore = true')
    expect(cardSource).toContain('setLight(id, state, { optimistic: optimisticStore })')
    expect(initSource).toContain('if (options.optimistic !== false)')
    // Don't flood repeated power-on events while an off light is dragged.
    expect(cardSource).toContain('!light.on && !dragPowerRequested')
    expect(home).toContain('href="#phone-lighting-title"')
    expect(home).toContain('href="#lighting-title"')
  })

  it('keeps room reveal inside Home with non-modal accessible navigation', () => {
    expect(home).toContain('selectedRoom === id ? null : id')
    expect(home).toContain('aria-expanded={selectedRoom === group.id}')
    expect(home).toContain('aria-controls={`phone-reveal-${group.id}`}')
    expect(home).toContain('<QuietAtlasHomeLightingReveal')
    expect(reveal).not.toContain('role="dialog"')
    expect(reveal).not.toContain('aria-modal')
    expect(reveal).toContain('prefers-reduced-motion:reduce')
    expect(controls).toContain('min-height:44px')
  })

  it('compiles the four source components without accessibility warnings', () => {
    for (const [filename, source] of [
      ['+page.svelte', root],
      ['classic/+page.svelte', classic],
      ['QuietAtlasHomeLightingReveal.svelte', reveal],
      ['QuietAtlasRoomControls.svelte', controls],
    ]) {
      expect(compile(source, { filename, generate: 'dom', css: 'external' }).warnings, filename).toEqual([])
    }
  })
})
