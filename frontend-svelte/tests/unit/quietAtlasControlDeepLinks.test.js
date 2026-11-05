import { describe, expect, it } from 'vitest'
import {
  controlGroupHref, lightingDetailHref, lightingDetailOrigin,
  isKnownLightingGroup, CONTROL_SCENES_HREF, parseControlIntent,
  activeQuietAtlasSection, isQuietAtlasReadOnlyPreview,
} from '../../src/lib/quietAtlas/navigation.js'
import { LIGHTING_GROUPS, buildLightingOverview } from '../../src/lib/quietAtlas/lightingModel.js'
import home from '../../src/routes/quiet-atlas/home/+page.svelte?raw'
import control from '../../src/routes/quiet-atlas/control/+page.svelte?raw'
import experience from '../../src/lib/components/QuietAtlasLightingExperience.svelte?raw'
import detail from '../../src/routes/quiet-atlas/lighting/[groupId]/+page.svelte?raw'

const parse = (query) => parseControlIntent(new URLSearchParams(query))

describe('Quiet Atlas non-modal Home and Control lighting links (#461)', () => {
  it('routes only known fixture groups, preserving a whitelisted origin', () => {
    expect(LIGHTING_GROUPS.map(({ id }) => id)).toEqual(['living', 'bedroom', 'kitchen', 'plant'])
    for (const { id } of LIGHTING_GROUPS) {
      expect(controlGroupHref(id)).toBe('/quiet-atlas/lighting/' + id + '?from=control')
      expect(lightingDetailHref(id, 'home')).toBe('/quiet-atlas/lighting/' + id + '?from=home')
      expect(parse('group=' + id)).toBe('group:' + id) // old bookmarked links
      expect(isKnownLightingGroup(id)).toBe(true)
      expect(isQuietAtlasReadOnlyPreview('/quiet-atlas/lighting/' + id)).toBe(true)
    }
    // Extra fixtures already appear as a read-only Control card; it must open.
    const other = buildLightingOverview({
      '7': { light_id: '7', name: 'Additional lamp', reachable: true, on: true, bri: 125 },
    }, true).find(({ id }) => id === 'other')
    expect(other?.fixtureIds).toEqual(['7'])
    expect(other?.supportsGroupWrite).toBe(false)
    expect(buildLightingOverview({}, true).some(({ id }) => id === 'other')).toBe(false)
    expect(isKnownLightingGroup('other')).toBe(true)
    expect(lightingDetailHref('other', 'control')).toBe('/quiet-atlas/lighting/other?from=control')
    expect(isQuietAtlasReadOnlyPreview('/quiet-atlas/lighting/other')).toBe(true)
    for (const value of ['__proto__', '../settings', '']) {
      expect(controlGroupHref(value)).toBe('/quiet-atlas/control')
      expect(lightingDetailHref(value, 'home')).toBe('/quiet-atlas/home')
      expect(isKnownLightingGroup(value)).toBe(false)
    }
    expect(lightingDetailHref('living', 'https://evil.test')).toBe('/quiet-atlas/lighting/living?from=control')
    expect(lightingDetailOrigin(new URLSearchParams('from=https://evil.test'))).toBe('control')
    expect(lightingDetailOrigin(new URLSearchParams('from=home'))).toBe('home')
    expect(lightingDetailOrigin(null)).toBe('control')
    expect(isQuietAtlasReadOnlyPreview('/quiet-atlas/lighting/future-functional')).toBe(false)
    expect(activeQuietAtlasSection('/quiet-atlas/lighting/living', '', new URLSearchParams('from=home'))).toBe('home')
    expect(activeQuietAtlasSection('/quiet-atlas/lighting/bedroom', '', new URLSearchParams('from=control'))).toBe('control')
  })

  it('keeps scene browsing and old group URLs read-only', () => {
    expect(CONTROL_SCENES_HREF).toBe('/quiet-atlas/control?view=scenes')
    expect(parse('view=scenes')).toBe('scenes')
    expect(parse('view=scenes&group=plant')).toBeNull()
    expect(parse('group=living&group=bedroom')).toBeNull()
    expect(parse('view=scenes&view=scenes')).toBeNull()
    expect(parse('view=apply')).toBeNull()
    expect(parse('group=other')).toBe('group:other')
    expect(parse('group=')).toBeNull()
    expect(parse('')).toBeNull()
    expect(parseControlIntent(null)).toBeNull()
  })

  it('never opens a group dialog from Home or Control, and Back is not an X-to-Control', () => {
    expect(home).toContain("href={lightingDetailHref(group.id, 'home')}")
    expect(home).toContain('href={CONTROL_SCENES_HREF}')
    expect(control).toContain('parseControlIntent($page.url.searchParams)')
    expect(experience).toContain("goto(lightingDetailHref(id, 'control'))")
    expect(experience).toContain("routeIntent?.startsWith('group:')")
    expect(experience).toContain('replaceState: true') // only legacy URL redirect
    expect(experience).not.toContain('<QuietAtlasGroupSheet')
    expect(detail).toContain('class="return-link" href={returnHref}')
    expect(detail).toContain('lightingDetailOrigin($page.url.searchParams)')
    expect(detail).toContain('<QuietAtlasGroupSheet inline={true} group={room}')
    const refreshCode = detail.slice(detail.indexOf('async function refresh()'), detail.indexOf('function onConnectionChanged('))
    expect(refreshCode).toContain('beginLightRead(snapshot)')
    expect(refreshCode).not.toContain('invalidateLightRead(snapshot)')
    expect(detail).toContain('snapshot = invalidateLightRead(snapshot)') // reconnect/visibility revoke evidence
    for (const source of [home, control, experience, detail]) {
      expect(source).not.toMatch(/\b(apiPost|apiPut|setLight|activateScene|hueWrite|light_command)\s*\(/)
    }
  })
})
