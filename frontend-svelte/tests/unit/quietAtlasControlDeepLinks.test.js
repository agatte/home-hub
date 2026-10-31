import { describe, expect, it } from 'vitest'
import {
  controlGroupHref,
  CONTROL_SCENES_HREF,
  parseControlIntent,
} from '../../src/lib/quietAtlas/navigation.js'
import { LIGHTING_GROUPS } from '../../src/lib/quietAtlas/lightingModel.js'
import home from '../../src/routes/quiet-atlas/home/+page.svelte?raw'
import control from '../../src/routes/quiet-atlas/control/+page.svelte?raw'
import experience from '../../src/lib/components/QuietAtlasLightingExperience.svelte?raw'

const parse = (query) => parseControlIntent(new URLSearchParams(query))

describe('Quiet Atlas read-only Home to Control detail links', () => {
  it('maps only known fixture groups to whitelisted destinations', () => {
    expect(LIGHTING_GROUPS.map(({ id }) => id)).toEqual(['living', 'bedroom', 'kitchen', 'plant'])
    for (const { id } of LIGHTING_GROUPS) {
      expect(controlGroupHref(id)).toBe('/quiet-atlas/control?group=' + id)
      expect(parse('group=' + id)).toBe('group:' + id)
    }
    expect(controlGroupHref('other')).toBe('/quiet-atlas/control')
    expect(controlGroupHref('__proto__')).toBe('/quiet-atlas/control')
    expect(controlGroupHref('../settings')).toBe('/quiet-atlas/control')
    expect(controlGroupHref('')).toBe('/quiet-atlas/control')
  })

  it('accepts only one valid read-only view or group parameter', () => {
    expect(CONTROL_SCENES_HREF).toBe('/quiet-atlas/control?view=scenes')
    expect(parse('view=scenes')).toBe('scenes')
    expect(parse('view=scenes&group=plant')).toBeNull()
    expect(parse('group=living&group=bedroom')).toBeNull()
    expect(parse('view=scenes&view=scenes')).toBeNull()
    expect(parse('view=apply')).toBeNull()
    expect(parse('group=other')).toBeNull()
    expect(parse('group=%5F%5Fproto%5F%5F')).toBeNull()
    expect(parse('group=')).toBeNull()
    expect(parse('')).toBeNull()
    expect(parseControlIntent(null)).toBeNull()
  })

  it('threads only navigational intent into existing read-only dialogs', () => {
    expect(home).toContain('href={controlGroupHref(group.id)}')
    expect(home).toContain('href={CONTROL_SCENES_HREF}')
    expect(control).toContain('parseControlIntent($page.url.searchParams)')
    expect(control).toContain('<QuietAtlasLightingExperience {routeIntent} />')
    expect(experience).toContain('routeIntent !== handledRouteIntent')
    expect(experience).toContain("routeIntent === 'scenes'")
    expect(experience).toContain("routeIntent?.startsWith('group:')")
    expect(experience).toContain('replaceState: true')
    expect(experience).not.toMatch(/\b(apiPost|setLight|activateScene|hueWrite)\s*\(/)
  })
})
