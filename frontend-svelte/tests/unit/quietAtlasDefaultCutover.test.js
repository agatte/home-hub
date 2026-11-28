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
  it('makes the designed Home the root and keeps only the Classic bookmark alias', () => {
    expect(root).toContain("import RedesignedHome from './quiet-atlas/home/+page.svelte'")
    expect(root).toContain('<RedesignedHome />')
    expect(classic).toContain('goto(destination, { replaceState: true })')
    expect(classic).not.toContain('<ApartmentWidget />')
    expect(classic).not.toContain('<ModeCardDeck />')
    expect(shouldUseQuietAtlasShell('/', new URLSearchParams())).toBe(true)
    expect(shouldUseQuietAtlasShell('/classic', new URLSearchParams('shell=quiet-atlas'))).toBe(true)
    expect(activeQuietAtlasSection('/')).toBe('home')
    expect(MORE_DESTINATIONS.find(x => x.id === 'apartment')?.href).toBe('/quiet-atlas/household')
    expect(shell).toContain("{ id: 'home', label: 'Home', href: '/'")
    expect(shouldShowGlobalErrorToast('/', new URLSearchParams())).toBe(true)
  })

  it('uses existing LightCard/WS controls for each actual fixture, with only the explicit kitchen pair linked', () => {
    expect(reveal).toContain('<QuietAtlasRoomControls room={group.id}')
    expect(reveal).not.toContain('Preview glow')
    expect(reveal).not.toContain('Preview on')
    expect(controls).toContain("import LightCard from './LightCard.svelte'")
    for (const mapping of ["living: ['1']", "bedroom: ['2', '5']", "kitchen: ['3', '4']", "plant: ['6']"]) {
      expect(controls).toContain(mapping)
    }
    expect(controls).toContain('<LightCard light={$lights[lightId]} optimisticStore={false} />')
    expect(controls.match(/linkedIds=/g)).toHaveLength(1)
    expect(controls).toContain("light={$lights['3']} linkedIds={['4']}")
    expect(controls).toContain('writeAllowed={linkedCanWrite}')
    expect(controls).not.toContain('<LightGrid')
    expect(controls).not.toContain('fetch(')
    expect(controls).not.toContain('apiPut(')
    expect(controls).toContain('!$connected')
    expect(controls).toContain('$lights[lightId].reachable === true')
    expect(controls).toContain('Light unavailable')
    expect(controls).toContain('Waiting for light status')
    expect(controls).toContain('$deviceStatus.light_command_results !== true')
    expect(controls).toContain('Lighting controls are unavailable until HomeHub is updated.')
    // No global optimistic patch in the new Home: a WS send is not an ACK.
    expect(cardSource).toContain('export let optimisticStore = false')
    expect(cardSource).toContain('void optimisticStore')
    expect(cardSource).toContain('function fanout(id, state)')
    expect(initSource).not.toContain('optimisticLightPatch(')
    expect(initSource).toContain('lightCommandTracker.submit(lightId, state')
    // No repeated power-on frames during an off-light drag: the guarded
    // request is sent only on pointer release, with power + brightness together.
    expect(cardSource).toContain('// Preview only; pointer release sends the guarded request.')
    expect(cardSource).toContain('if (wasDrag && finalBri != null)')
    expect(cardSource).toContain('fanout(light.light_id, light.on ? { bri } : { on: true, bri })')
    expect(home).toContain('id="phone-lighting-title"')
    expect(home).toContain('id="lighting-title"')
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
