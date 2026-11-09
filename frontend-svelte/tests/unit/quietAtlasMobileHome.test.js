import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import home from '../../src/routes/quiet-atlas/home/+page.svelte?raw'
import reveal from '../../src/lib/components/QuietAtlasHomeLightingReveal.svelte?raw'
import { lightingDetailHref, CONTROL_SCENES_HREF } from '../../src/lib/quietAtlas/navigation.js'

describe('Quiet Atlas phone-first Home composition', () => {
  it('uses a genuinely distinct phone hierarchy without reordering keyboard focus', () => {
    const marker = (text) => home.indexOf(text)
    expect(marker('class="phone-status"')).toBeGreaterThan(marker('<header class="foreword">'))
    expect(marker('class="phone-actions"')).toBeGreaterThan(marker('class="phone-status"'))
    expect(marker('class="phone-apartment-entry"')).toBeGreaterThan(marker('class="phone-actions"'))
    expect(marker('class="apartment-stage"')).toBeGreaterThan(marker('class="phone-apartment-entry"'))
    expect(home).toContain('.phone-status,.phone-actions,.phone-apartment-entry {display:none;}')
    expect(home).toContain('.phone-status,.phone-actions,.phone-apartment-entry {display:block;min-width:0;}')
    expect(home).toContain('.apartment-stage,.lighting-dock {display:none;}')
    expect(home).toContain('.desktop-home-heading {display:none;}')
    expect(home).toContain('.mobile-home-heading {display:inline;}')
    expect(home).not.toMatch(/\border:\s*[0-9]+\s*;/)
  })

  it('presents source-qualified context and never claims sensor or bridge authority', () => {
    expect(home).toContain('aria-label="Reported HomeHub status"')
    expect(home).toContain("contextDisplay.status === 'recent' ? 'Recent report' : 'Not verified'")
    expect(home).toContain('{contextDisplay.house}')
    expect(home).toContain('{contextDisplay.activity}')
    expect(home).toContain('A recent REST response is not proof of sensor freshness or room location.')
    expect(home).toContain('Design preview only — no light changes.')
    expect(home).not.toMatch(/\b(apiPost|apiPut|setLight|activateScene|hueWrite)\s*\(/)
  })

  it('keeps rooms/presets prominent, readable and tap-sized without group fanout', () => {
    expect(home).toContain('aria-label="Browse lighting by room"')
    expect(home).not.toContain('lightingDetailHref')
    const phone = home.slice(home.indexOf('<div class="phone-rooms"'), home.indexOf('<a class="phone-scenes"'))
    expect(phone).toContain('<button type="button"')
    expect(phone).toContain('aria-controls={`phone-reveal-${group.id}`}')
    expect(phone.indexOf('<QuietAtlasHomeLightingReveal')).toBeGreaterThan(phone.indexOf('</button>'))
    expect(phone.indexOf('<QuietAtlasHomeLightingReveal')).toBeLessThan(phone.indexOf('{/each}'))
    expect(phone).not.toContain('href={lightingDetailHref')
    expect(home).toContain('href={CONTROL_SCENES_HREF}')
    expect(lightingDetailHref('bedroom', 'home')).toBe('/quiet-atlas/lighting/bedroom?from=home')
    expect(CONTROL_SCENES_HREF).toBe('/quiet-atlas/control?view=scenes')
    for (const label of ['Living', 'Bedroom', 'Kitchen', 'Plant']) {
      expect(home).toContain("name: '" + label + "'")
    }
    expect(home).toContain('.phone-rooms {display:grid;grid-template-columns:minmax(0,1fr);')
    expect(home).toContain('.phone-room {display:flex;align-items:center;gap:15px;min-height:76px;box-sizing:border-box;')
    expect(home).toContain('.phone-scenes {min-height:64px;')
    expect(home).toContain('.phone-functional-handoff {min-height:50px;')
    expect(home).toContain('href="/#apartment-controls"')
    expect(home).toContain('Adjust lights now')
    expect(home).toContain('href="/"')
    expect(home).toContain('Apartment Canvas (#192)')
  })

  it('compiles in Svelte with zero warnings and leaves existing status lifecycle intact', () => {
    const result = compile(home, { filename: 'QuietAtlasPhoneHome.svelte', generate: 'dom', css: 'external' })
    expect(result.warnings).toEqual([])
    for (const generate of ['dom', 'ssr']) {
      expect(compile(reveal, { filename: 'QuietAtlasHomeLightingReveal.svelte', generate, css: 'external' }).warnings).toEqual([])
    }
    expect(home).toContain("fetch('/api/automation/status'")
    expect(home).toContain('newHomeContextSnapshot')
    expect(home).toContain('newRecentActivityLog')
    expect(home).toContain('window.clearInterval(pollTimer)')
    expect(home).toContain('prefers-reduced-motion:reduce')
  })
})
