import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import control from '../../src/routes/quiet-atlas/control/+page.svelte?raw'
import home from '../../src/routes/+page.svelte?raw'
import apartment from '../../src/lib/components/ApartmentWidget.svelte?raw'

describe('Quiet Atlas handoff to working lighting controls (#461)', () => {
  it('exposes one primary working-controls destination without claiming the preview writes', () => {
    expect(control).toContain('href="/#apartment-controls"')
    expect(control).toContain('Adjust lights now')
    expect(control).toContain('still a read-only preview')
    expect(control.match(/href="\/#apartment-controls"/g)).toHaveLength(1)
    expect(control).not.toMatch(/(?:apiPut|apiPost|light_command|activateScene|setLight)\s*\(/)
  })

  it('lands at the existing functional Apartment controls, not an invented actuator', () => {
    expect(home).toContain('id="apartment-controls"')
    expect(home).toContain('<ApartmentWidget />')
    expect(apartment).toContain('<LightGrid />')
    expect(apartment).toContain('<SceneBrowser')
    expect(home.match(/id="apartment-controls"/g)).toHaveLength(1)
  })

  it('preserves accessible phone action and compiles both pages without new warnings', () => {
    expect(control).toContain('min-height: 56px')
    expect(control).toContain('.live-lighting-link:focus-visible')
    for (const [filename, source] of [['quiet-atlas/control/+page.svelte', control], ['+page.svelte', home]]) {
      const result = compile(source, { filename, generate: 'dom', css: 'external' })
      expect(result.warnings).toEqual([])
    }
  })
})
