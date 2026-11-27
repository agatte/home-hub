import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import control from '../../src/routes/quiet-atlas/control/+page.svelte?raw'
import home from '../../src/routes/+page.svelte?raw'
import classic from '../../src/routes/classic/+page.svelte?raw'
import lighting from '../../src/lib/components/QuietAtlasLightingExperience.svelte?raw'
import sceneTools from '../../src/lib/components/QuietAtlasSceneTools.svelte?raw'
import roomControls from '../../src/lib/components/QuietAtlasRoomControls.svelte?raw'

describe('Quiet Atlas handoff to working lighting controls (#461)', () => {
  it('uses the existing guarded controls in the redesigned Control route', () => {
    expect(control).not.toContain('href="/classic#apartment-controls"')
    expect(control).not.toContain('Adjust lights now')
    expect(control).toContain('<QuietAtlasLightingExperience {routeIntent} functional={true} />')
    expect(control).not.toContain('still a read-only preview')
    expect(control).not.toMatch(/(?:apiPut|apiPost|light_command|activateScene|setLight)\s*\(/)
  })

  it('does not route supported room controls back to Classic', () => {
    expect(roomControls).not.toContain('/classic')
    expect(roomControls).toContain('light_command_results !== true')
    expect(roomControls).toContain('Opening a room does not change any lights.')
    expect(compile(roomControls,{generate:'dom',css:'external'}).warnings).toEqual([])
  })
  it('maps the retired Apartment bookmark to the existing guarded Control surface', () => {
    expect(home).toContain("import RedesignedHome from './quiet-atlas/home/+page.svelte'")
    expect(classic).toContain('classicBookmarkHref(window.location.hash)')
    expect(classic).not.toContain('<ApartmentWidget />')
    expect(lighting).toContain('<QuietAtlasSceneBrowser {functional}')
    expect(sceneTools).toContain("await apiPost('/api/scenes/try/cancel', {})")
  })

  it('preserves accessible phone action and compiles both pages without new warnings', () => {
    expect(control).toContain('Adjust lights by room')
    expect(control).toContain('functional={true}')
    for (const [filename, source] of [['quiet-atlas/control/+page.svelte', control], ['+page.svelte', home], ['classic/+page.svelte', classic]]) {
      const result = compile(source, { filename, generate: 'dom', css: 'external' })
      expect(result.warnings).toEqual([])
    }
  })
})
