import { describe, it, expect } from 'vitest'
import shellSource from '../../src/lib/components/QuietAtlasShell.svelte?raw'
import homeSource from '../../src/routes/quiet-atlas/home/+page.svelte?raw'
import {
  MORE_DESTINATIONS,
  hasMoreParent,
  activeQuietAtlasSection,
  shouldUseQuietAtlasShell,
  shouldShowGlobalErrorToast,
  withQuietAtlasShell,
  isQuietAtlasReadOnlyPreview,
} from '../../src/lib/quietAtlas/navigation.js'

describe('Quiet Atlas shared shell navigation', () => {
  it('uses the redesigned shell for owner routes and preserves special route layouts', () => {
    expect(shouldUseQuietAtlasShell('/quiet-atlas', new URLSearchParams())).toBe(true)
    expect(shouldUseQuietAtlasShell('/music', new URLSearchParams('shell=quiet-atlas'))).toBe(true)
    expect(shouldUseQuietAtlasShell('/settings', new URLSearchParams('shell=quiet-atlas'))).toBe(true)
    expect(shouldUseQuietAtlasShell('/', new URLSearchParams())).toBe(true)
    expect(shouldUseQuietAtlasShell('/classic', new URLSearchParams())).toBe(true)
    expect(shouldUseQuietAtlasShell('/gameday', new URLSearchParams('shell=quiet-atlas'))).toBe(false)
    expect(shouldUseQuietAtlasShell('/gameday/prototype', new URLSearchParams('shell=quiet-atlas'))).toBe(false)
    expect(shouldUseQuietAtlasShell('/guest/wifi', new URLSearchParams('shell=quiet-atlas'))).toBe(false)
  })

  it('keeps global API error toasts off isolated review surfaces', () => {
    expect(shouldShowGlobalErrorToast('/quiet-atlas/control', new URLSearchParams())).toBe(true)
    expect(shouldShowGlobalErrorToast('/quiet-atlas', new URLSearchParams())).toBe(false)
    expect(shouldShowGlobalErrorToast('/quiet-atlas/home', new URLSearchParams())).toBe(true)
    expect(shouldShowGlobalErrorToast('/music', new URLSearchParams('shell=quiet-atlas'))).toBe(true)
    expect(shouldShowGlobalErrorToast('/analytics', new URLSearchParams('shell=quiet-atlas'))).toBe(true)
    expect(shouldShowGlobalErrorToast('/settings', new URLSearchParams('shell=quiet-atlas'))).toBe(true)
    expect(shouldShowGlobalErrorToast('/gameday/prototype', new URLSearchParams())).toBe(false)
    expect(shouldShowGlobalErrorToast('/music', new URLSearchParams())).toBe(true)
    expect(shouldShowGlobalErrorToast('/', new URLSearchParams())).toBe(true)
  })

  it('labels only known read-only reviews as previews and keeps functional warnings visible', () => {
    for (const route of [
      '/quiet-atlas',
    ]) {
      expect(isQuietAtlasReadOnlyPreview(route)).toBe(true)
      expect(shouldShowGlobalErrorToast(route, new URLSearchParams())).toBe(false)
    }
    for (const route of ['/quiet-atlas/insights', '/quiet-atlas/settings', '/quiet-atlas/music', '/music', '/settings', '/analytics', '/journal', '/personality', '/quiet-atlas/control', '/quiet-atlas/lighting/bedroom', '/quiet-atlas/future-functional']) {
      expect(isQuietAtlasReadOnlyPreview(route)).toBe(false)
      expect(shouldShowGlobalErrorToast(route, new URLSearchParams('shell=quiet-atlas'))).toBe(true)
    }
    expect(shellSource).toContain('readOnlyPreview = isQuietAtlasReadOnlyPreview($page.url.pathname)')
    expect(shellSource).toContain("'Read-only design preview' : 'Existing HomeHub tools · changes possible'")
    expect(shellSource).toContain("'Read-only preview' : 'HomeHub controls'")
  })

  it('keeps More a real modal across mobile and desktop without locking scrolling after close', () => {
    expect(shellSource).toContain('<aside class="qa-sidebar" aria-label="HomeHub navigation" inert={moreOpen}>')
    expect(shellSource).toContain('<div class="qa-main" inert={moreOpen}>')
    expect(shellSource).toContain('<nav class="qa-mobile-nav" aria-label="Primary navigation" inert={moreOpen}>')
    expect(shellSource).toContain('role="dialog"')
    expect(shellSource).toContain('aria-modal="true"')
    expect(shellSource).toContain('overscroll-behavior: contain;')
    expect(shellSource).toContain(':global(body:has(.qa-more-panel)) { overflow: hidden; }')
    expect(shellSource).toContain("if (previousRoute !== null && route !== previousRoute && moreOpen) closeMore(false)")
    expect(shellSource).toContain('if (returnFocus?.isConnected) returnFocus.focus()')
    expect(shellSource).toContain('max-height: min(82dvh, 720px);')
  })

  it('connects preview Home, Control, groups, and scene navigation without changing legacy URLs', () => {
    expect(shellSource).toContain("id: 'home', label: 'Home', href: '/'")
    expect(shellSource).toContain("id: 'control', label: 'Control', href: '/quiet-atlas/control'")
    expect(shellSource).toContain("id: 'music', label: 'Music', href: '/quiet-atlas/music'")
    expect(shellSource.match(/href="\/"/g)).toHaveLength(2)
    expect(shellSource).toContain('if (previousRoute !== null && route !== previousRoute && moreOpen) closeMore(false)')
    expect(shellSource).toContain('return unsubscribe')
    expect(homeSource).not.toContain('Control · precision workspace')
    expect(homeSource).toContain('class="browse-link" href="/quiet-atlas/control">Browse Control')
    expect(homeSource).not.toContain("href={lightingDetailHref(group.id, 'home')}")
    expect(homeSource).not.toContain('href="/quiet-atlas"') // obsolete preview link removed
    expect(activeQuietAtlasSection('/quiet-atlas/home')).toBe('home')
    expect(activeQuietAtlasSection('/')).toBe('home')
    expect(activeQuietAtlasSection('/quiet-atlas/control')).toBe('control')
    expect(activeQuietAtlasSection('/quiet-atlas')).toBe('control')
  })

  it('preserves query strings and fragments when opting into the shell', () => {
    expect(withQuietAtlasShell('/music')).toBe('/music?shell=quiet-atlas')
    expect(withQuietAtlasShell('/settings?section=audio#top')).toBe('/settings?section=audio&shell=quiet-atlas#top')
    expect(withQuietAtlasShell('/music?shell=old#library')).toBe('/music?shell=quiet-atlas#library')
  })

  it('keeps current and future nav destinations mapped to existing routes', () => {
    expect(activeQuietAtlasSection('/quiet-atlas/home')).toBe('home')
    expect(activeQuietAtlasSection('/')).toBe('home')
    expect(activeQuietAtlasSection('/quiet-atlas')).toBe('control')
    expect(activeQuietAtlasSection('/quiet-atlas', '#control')).toBe('control')
    expect(activeQuietAtlasSection('/quiet-atlas/home', '#control')).toBe('home')
    expect(activeQuietAtlasSection('/music', '#control')).toBe('music')
    expect(activeQuietAtlasSection('/analytics', '#control')).toBe('insights')
    expect(activeQuietAtlasSection('/settings', '#control')).toBe('more')
    expect(activeQuietAtlasSection('/quiet-atlas/control')).toBe('control')
    expect(activeQuietAtlasSection('/quiet-atlas/music')).toBe('music')
    expect(shouldUseQuietAtlasShell('/quiet-atlas/music', new URLSearchParams())).toBe(true)
    expect(shouldUseQuietAtlasShell('/quiet-atlas/control', new URLSearchParams())).toBe(true)
    expect(activeQuietAtlasSection('/music')).toBe('music')
    expect(activeQuietAtlasSection('/analytics')).toBe('insights')
    expect(activeQuietAtlasSection('/settings')).toBe('more')
    expect(activeQuietAtlasSection('/quiet-atlas/settings')).toBe('more')
    expect(MORE_DESTINATIONS.map(({ href }) => href)).toEqual([
      '/quiet-atlas/settings', '/quiet-atlas/journal', '/quiet-atlas/personalization', '/quiet-atlas/household', '/gameday', '/guest',
    ])
    expect(MORE_DESTINATIONS.filter((item) => item.shell)).toEqual([])
  })
})

it('only provides the More parent for explicit More workspaces', () => {
  for (const path of ['/settings','/journal','/personality','/quiet-atlas/settings','/quiet-atlas/journal','/quiet-atlas/personalization','/quiet-atlas/household']) expect(hasMoreParent(path)).toBe(true)
  for (const path of ['/','/quiet-atlas/control','/quiet-atlas/lighting/bedroom','/quiet-atlas/music/artist-review','/classic','/guest','/gameday','/quiet-atlas/future']) expect(hasMoreParent(path)).toBe(false)
  expect(shellSource).toContain('hasMoreParent($page.url.pathname)')
  expect(shellSource).toContain('aria-label="Back to More destinations"')
  expect(shellSource).toContain('on:click={openMore}')
})
