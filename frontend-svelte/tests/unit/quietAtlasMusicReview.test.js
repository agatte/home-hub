import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import musicReview from '../../src/routes/quiet-atlas/music/+page.svelte?raw'
import functionalMusic from '../../src/routes/music/+page.svelte?raw'
import approvedEntry from '../../src/lib/components/ApprovedAppleMusicEntry.svelte?raw'
import shellSource from '../../src/lib/components/QuietAtlasShell.svelte?raw'
import {
  activeQuietAtlasSection,
  isQuietAtlasReadOnlyPreview,
  shouldShowGlobalErrorToast,
  shouldUseQuietAtlasShell,
  withQuietAtlasShell,
} from '../../src/lib/quietAtlas/navigation.js'

describe('Quiet Atlas Music design-review route', () => {
  it('makes the primary Music tab a truthful opt-in review and preserves functional Music', () => {
    expect(shellSource).toContain("id: 'music', label: 'Music', href: '/quiet-atlas/music'")
    expect(activeQuietAtlasSection('/quiet-atlas/music')).toBe('music')
    expect(activeQuietAtlasSection('/music')).toBe('music')
    expect(isQuietAtlasReadOnlyPreview('/quiet-atlas/music')).toBe(true)
    expect(isQuietAtlasReadOnlyPreview('/music')).toBe(false)
    expect(shouldUseQuietAtlasShell('/quiet-atlas/music', new URLSearchParams())).toBe(true)
    expect(shouldShowGlobalErrorToast('/quiet-atlas/music', new URLSearchParams())).toBe(false)
    expect(shouldShowGlobalErrorToast('/music', new URLSearchParams('shell=quiet-atlas'))).toBe(true)
    expect(musicReview).toContain("withQuietAtlasShell('/music')")
    expect(musicReview).toContain("withQuietAtlasShell('/music#approved-apple-track')")
    expect(withQuietAtlasShell('/music#approved-apple-track')).toBe('/music?shell=quiet-atlas#approved-apple-track')
    expect(functionalMusic).toContain('ApprovedAppleMusicEntry')
    expect(approvedEntry).toContain('id="approved-apple-track"')
  })

  it('is a static navigation surface with clear functional handoff and no misleading music status', () => {
    expect(musicReview).toContain('READ-ONLY DESIGN REVIEW')
    expect(musicReview).toContain('Existing tools are functional and may change preferences')
    expect(musicReview).toContain('no live track or speaker state')
    expect(musicReview).toContain('No catalog, personal taste, source availability')
    expect(musicReview).toContain('aria-label="Current music destinations"')
    expect(musicReview).toContain('href="/quiet-atlas/home"')
    expect(musicReview).toContain('min-height:48px')
    expect(musicReview).toContain('@media(max-width:600px)')
    expect(musicReview).toContain('@media(prefers-reduced-motion:reduce)')
    expect(musicReview).not.toMatch(/\b(fetch|apiGet|apiPost|apiPut|apiDelete|goto|setLight|activateScene|hueWrite)\s*\(/)
    expect(musicReview).not.toMatch(/\bon:(click|change|submit|input)\s*=/)
  })

  it('compiles the actual Svelte page without warnings and leaves playback components untouched', () => {
    const result = compile(musicReview, { filename: 'QuietAtlasMusicReview.svelte', generate: 'dom', css: 'external' })
    expect(result.warnings).toEqual([])
    expect(functionalMusic).toContain('ShadowDiscoveryPanel')
    expect(functionalMusic).toContain('ApprovedAppleMusicEntry')
    expect(functionalMusic).toContain('PrepareSonosAction')
    expect(functionalMusic).toContain('MusicBanditDiagnostics')
  })
})
