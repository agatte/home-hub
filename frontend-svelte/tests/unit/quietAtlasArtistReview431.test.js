// @ts-ignore -- Node test-runtime built-in; frontend svelte-check has no Node types.
import { createHash } from 'node:crypto'
// @ts-ignore -- Node test-runtime built-in; frontend svelte-check has no Node types.
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'

import landing from '../../src/routes/quiet-atlas/music/+page.svelte?raw'
import review from '../../src/routes/quiet-atlas/music/artist-review/+page.svelte?raw'
import {
  activeQuietAtlasSection,
  isQuietAtlasReadOnlyPreview,
  shouldShowGlobalErrorToast,
  shouldUseQuietAtlasShell,
} from '../../src/lib/quietAtlas/navigation.js'

const REVIEW_ROUTE = '/quiet-atlas/music/artist-review'

describe('#431 Quiet Atlas fictional artist identity preview', () => {
  it('has an explicit, nonfunctional entry point under the real Music review', () => {
    expect(landing).toContain('href="/quiet-atlas/music/artist-review"')
    expect(landing).toContain('Preview fictional artist matching')
    expect(landing).toContain("withQuietAtlasShell('/music')")
    expect(landing).toContain('withQuietAtlasShell(\'/music#approved-apple-track\')')
    expect(activeQuietAtlasSection(REVIEW_ROUTE)).toBe('music')
    expect(isQuietAtlasReadOnlyPreview(REVIEW_ROUTE)).toBe(true)
    expect(shouldShowGlobalErrorToast(REVIEW_ROUTE, new URLSearchParams())).toBe(false)
    expect(shouldUseQuietAtlasShell(REVIEW_ROUTE, new URLSearchParams())).toBe(true)
    expect(isQuietAtlasReadOnlyPreview('/music')).toBe(false)
  })

  it('only uses four known invented labels and one fictional result set per label', () => {
    for (const label of [
      'Imaginary Atlas Ensemble', 'Fictional Pattern Unit',
      'Invented Sound Group', 'Makebelieve Echo Collective',
    ]) expect(review).toContain(label)

    expect(review).toContain('const fixtures = [[0], [1], [2, 3], [4]]')
    expect(review).toContain('DemoCatalog (fictional)')
    expect(review).toContain('Identical artist names do not prove identical identities.')
    expect(review).toContain('row.chosen === null')
    expect(review).toContain('None look right / I\'m not sure')
    expect(review).toContain("if (step !== 'consent' || pending !== index) return")
    expect(review).toContain('pending = null')
    expect(review).toContain("step = 'intro'")
    expect(review).toContain("rows = fresh()")
    expect(review).toContain('aria-live="polite"')
    expect(review).toContain('type="radio"')
    expect(review).toContain('Cancel this search')
    expect(review).toContain('Undo this match')
    expect(review).toContain('Close / discard')
  })

  it('is an ephemeral simulation, never an implicit external query or preference writer', () => {
    expect(review).not.toMatch(/\b(fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon|apiGet|apiPost|apiPut|apiDelete|setLight|activateScene|goto)\s*\(/)
    expect(review).not.toMatch(/\b(localStorage|sessionStorage|indexedDB|document\.cookie|navigator\.sendBeacon)\b/)
    expect(review).not.toMatch(/from\s+['"]\$lib\/(stores|api|services)\//)
    expect(review).not.toMatch(/\b(artist_id|catalog_id|music_taste|sonos_)\s*=/i)
    expect(review).toContain('Nothing saved.')
    expect(review).toContain('No real catalog connection.')
  })

  it('uses only the human-approved noncircular Listening Room artwork', () => {
    expect(review).toContain('src="/design-review/artist-light-waves-431.png"')
    expect(review).toContain('alt="" aria-hidden="true"')
    const png = readFileSync(new URL('../../static/design-review/artist-light-waves-431.png', import.meta.url))
    expect(png.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a')
    expect(png.readUInt32BE(16)).toBe(178)
    expect(png.readUInt32BE(20)).toBe(178)
    expect(createHash('sha256').update(png).digest('hex')).toBe(
      '7961945678f4e3ee0a6ebbd65da6cf6b0270914022deba8890697505175306f0'
    )
    expect(review).not.toContain('class="disc"')
  })

  it('uses one container-relative scale and no decorative action arrows', () => {
    expect(review).toContain('max-width: 1160px')
    expect(review).toContain('--rail-width: clamp(')
    expect(review).toContain('--art-width: clamp(')
    expect(review).toContain('--read-width: clamp(')
    expect(review).toContain('grid-template-columns: minmax(0, 1fr) var(--rail-width)')
    expect(review).toContain('max-width: var(--read-width)')
    expect(review).toContain('width: min(100%, var(--art-width))')
    expect(review).toContain('max-height: clamp(')
    expect(review).toContain('overflow-y: auto')
    expect(review).toContain('max-height: none; overflow: visible;')
    expect(review).not.toContain('↗')
    expect(review).not.toContain('←')
    expect(review).not.toContain('→')
    expect(review).not.toContain('↻')
  })

  it('compiles both actual Svelte pages without warnings and provides responsive keyboard UI', () => {
    for (const [name, source] of [['Music review', landing], ['Fictional artist review', review]]) {
      const compiled = compile(source, {
        filename: name + '.svelte', generate: 'dom', css: 'external',
      })
      expect(compiled.warnings).toEqual([])
    }
    expect(review).toContain('container-type: inline-size')
    expect(review).toContain('@container (max-width: 800px)')
    expect(review).toContain('@container (max-width: 420px)')
    expect(review).toContain('@media (prefers-reduced-motion: reduce)')
    expect(review).toContain('event.key === \'Escape\'')
    expect(review).toMatch(/min-height:\s*44px/)
    expect(review).toMatch(/min-height:\s*52px/)
    expect(review).toContain('focus-visible')
  })
})
