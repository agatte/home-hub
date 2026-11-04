import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import home from '../../src/routes/quiet-atlas/home/+page.svelte?raw'
import control from '../../src/routes/quiet-atlas/control/+page.svelte?raw'
import insights from '../../src/routes/quiet-atlas/insights/+page.svelte?raw'
import settings from '../../src/routes/quiet-atlas/settings/+page.svelte?raw'

describe('Quiet Atlas task-first route hierarchy (#157)', () => {
  it('offers working lighting before phone browsing and keeps Apartment separate', () => {
    const phone = home.slice(home.indexOf('<section class="phone-actions"'), home.indexOf('<section class="phone-apartment-entry"'))
    expect(phone.indexOf('href="/#apartment-controls"')).toBeGreaterThan(-1)
    expect(phone.indexOf('href="/#apartment-controls"')).toBeLessThan(phone.indexOf('<nav'))
    expect(phone).toContain('Adjust lights now')
    expect(phone).toContain('href={controlGroupHref(group.id)}')
    expect(phone).toContain('href={CONTROL_SCENES_HREF}')
    expect(home).toContain('class="working-lighting-link" href="/#apartment-controls"')
    expect(home).toContain('SPATIAL PLACEHOLDER · NOT A FLOOR PLAN')
    expect(home).toContain('Open Apartment &amp; household tools')
    expect(control).toContain('href="/#apartment-controls"')
    expect(control).toContain('<QuietAtlasLightingExperience {routeIntent} />')
  })

  it('keeps future explanation closed on desktop too, with real reports outside it', () => {
    expect(insights).toContain('let studyOpen = false')
    expect(insights).toContain('aria-expanded={studyOpen}')
    expect(insights).toContain('Future explanation layers')
    expect(insights).toContain('Proposed model · not a live decision trace.')
    const beforeStudy = insights.slice(0, insights.indexOf('<aside class="mechanism"'))
    expect(beforeStudy).toContain('<InsightsContextReadout />')
    expect(beforeStudy).toContain('{activity.message}')
    expect(beforeStudy).toContain('Receipt freshness applies to this request')
    const css = compile(insights, { css: 'external' }).css.code
    // The default rule must precede all media queries, so hiding is not phone-only.
    expect(css.indexOf('.study-content.phone-collapsed')).toBeLessThan(css.indexOf('@media'))
    expect(insights).toContain('href="/analytics?shell=quiet-atlas"')
  })

  it('preserves all eleven original settings destinations in the same task groups', () => {
    const groups = [...settings.matchAll(/id: '([^']+)',\s+index:/g)].map(m => m[1])
    expect(groups).toEqual(['behavior', 'experience', 'system'])
    const sections = [...settings.matchAll(/id: '([^']+)', label:/g)].map(m => m[1])
    expect(sections).toEqual(['automation', 'dnd', 'schedule', 'modes', 'music', 'audio', 'learning', 'gameday', 'overview', 'host', 'network'])
    expect(settings).toContain('<h1>Settings</h1>')
    expect(settings.match(/withQuietAtlasShell\('\/settings'\)/g)).toHaveLength(1)
    expect(settings).toContain("withQuietAtlasShell('/settings?section=' + item.id)")
    expect(settings).toContain('aria-expanded={expandedGroup === group.id}')
  })

  it('keeps the four routes read-only and compiles without warnings', () => {
    for (const [name, source] of Object.entries({ home, control, insights, settings })) {
      expect(source.match(/<h1[> ]/g), name).toHaveLength(1)
      expect(source, name).not.toMatch(/\b(apiPost|apiPut|setLight|activateScene|hueWrite)\s*\(/)
      expect(source, name).not.toMatch(/method:\s*['"](?:POST|PUT|PATCH|DELETE)/i)
      expect(compile(source, { filename: name + '.svelte', css: 'external' }).warnings, name).toEqual([])
    }
  })
})
