import { describe, it, expect } from 'vitest'
import {
  MORE_DESTINATIONS,
  activeQuietAtlasSection,
  shouldUseQuietAtlasShell,
  shouldShowGlobalErrorToast,
  withQuietAtlasShell,
} from '../../src/lib/quietAtlas/navigation.js'

describe('Quiet Atlas shared shell navigation', () => {
  it('keeps the new Home preview opt-in and preserves special route layouts', () => {
    expect(shouldUseQuietAtlasShell('/quiet-atlas', new URLSearchParams())).toBe(true)
    expect(shouldUseQuietAtlasShell('/music', new URLSearchParams('shell=quiet-atlas'))).toBe(true)
    expect(shouldUseQuietAtlasShell('/settings', new URLSearchParams('shell=quiet-atlas'))).toBe(true)
    expect(shouldUseQuietAtlasShell('/', new URLSearchParams())).toBe(false)
    expect(shouldUseQuietAtlasShell('/gameday', new URLSearchParams('shell=quiet-atlas'))).toBe(false)
    expect(shouldUseQuietAtlasShell('/gameday/prototype', new URLSearchParams('shell=quiet-atlas'))).toBe(false)
    expect(shouldUseQuietAtlasShell('/guest/wifi', new URLSearchParams('shell=quiet-atlas'))).toBe(false)
  })

  it('keeps global API error toasts off isolated review surfaces', () => {
    expect(shouldShowGlobalErrorToast('/quiet-atlas/control', new URLSearchParams())).toBe(false)
    expect(shouldShowGlobalErrorToast('/music', new URLSearchParams('shell=quiet-atlas'))).toBe(false)
    expect(shouldShowGlobalErrorToast('/gameday/prototype', new URLSearchParams())).toBe(false)
    expect(shouldShowGlobalErrorToast('/music', new URLSearchParams())).toBe(true)
    expect(shouldShowGlobalErrorToast('/', new URLSearchParams())).toBe(true)
  })

  it('preserves query strings and fragments when opting into the shell', () => {
    expect(withQuietAtlasShell('/music')).toBe('/music?shell=quiet-atlas')
    expect(withQuietAtlasShell('/settings?section=audio#top')).toBe('/settings?section=audio&shell=quiet-atlas#top')
    expect(withQuietAtlasShell('/music?shell=old#library')).toBe('/music?shell=quiet-atlas#library')
  })

  it('keeps current and future nav destinations mapped to existing routes', () => {
    expect(activeQuietAtlasSection('/quiet-atlas')).toBe('home')
    expect(activeQuietAtlasSection('/quiet-atlas', '#control')).toBe('control')
    expect(activeQuietAtlasSection('/quiet-atlas/control')).toBe('control')
    expect(shouldUseQuietAtlasShell('/quiet-atlas/control', new URLSearchParams())).toBe(true)
    expect(activeQuietAtlasSection('/music')).toBe('music')
    expect(activeQuietAtlasSection('/analytics')).toBe('insights')
    expect(activeQuietAtlasSection('/settings')).toBe('more')
    expect(MORE_DESTINATIONS.map(({ href }) => href)).toEqual([
      '/settings', '/journal', '/personality', '/', '/gameday', '/guest',
    ])
    expect(MORE_DESTINATIONS.filter((item) => item.shell).map((item) => item.href)).toEqual([
      '/settings', '/journal', '/personality',
    ])
  })
})
