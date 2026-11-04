import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import shell from '../../src/lib/components/QuietAtlasShell.svelte?raw'
import { MORE_DESTINATIONS } from '../../src/lib/quietAtlas/navigation.js'

describe('phone-native More navigation sheet (#461)', () => {
  it('preserves all six existing destinations and keeps Music routing out of scope', () => {
    expect(MORE_DESTINATIONS.map((item) => item.id)).toEqual([
      'settings', 'journal', 'personality', 'apartment', 'gameday', 'guest',
    ])
    expect(shell).toContain('MORE_DESTINATIONS.map((item) => ({')
    expect(shell).toContain('href: item.shell ? withQuietAtlasShell(item.href) : item.href')
    expect(shell).toContain('href={destination.href}')
    expect(shell).toContain('on:click={() => closeMore(false)}')
  })

  it('retains the existing modal, route transition, Escape and focus restoration contracts', () => {
    expect(shell).toContain('role="dialog"')
    expect(shell).toContain('aria-modal="true"')
    expect(shell).toContain('aria-labelledby="qa-more-title"')
    expect(shell).toContain('aria-expanded={moreOpen}')
    expect(shell).toContain('aria-controls="qa-more-panel"')
    expect(shell).toContain('inert={moreOpen}')
    expect(shell).toContain("if (event.key !== 'Tab' || !panel) return")
    expect(shell).toContain('last.focus()')
    expect(shell).toContain('first.focus()')
    expect(shell).toContain('closeButton?.focus()')
    expect(shell).toContain('aria-label="Close More destinations" on:click={() => closeMore()}')
    expect(shell).toContain("class:active={activeSection === 'more' || moreOpen}")
    expect(shell).toContain("if (event.key === 'Escape')")
    expect(shell).toContain("if (returnFocus?.isConnected) returnFocus.focus()")
    expect(shell).toContain('if (previousRoute !== null && route !== previousRoute && moreOpen) closeMore(false)')
    expect(shell).toContain(':global(body:has(.qa-more-panel)) { overflow: hidden; }')
  })

  it('keeps close affordance visible inside the scrollable mobile sheet', () => {
    expect(shell).toContain('max-height: min(82dvh, 720px);')
    expect(shell).toContain('overflow-y: auto;')
    expect(shell).toContain('overscroll-behavior: contain;')
    expect(shell).toContain('scroll-padding-top: 88px;')
    expect(shell).toContain('position: sticky;')
    expect(shell).toContain('z-index: 2;')
    expect(shell).toContain('.qa-close-more { flex: 0 0 48px; width: 48px; height: 48px; }')
    expect(shell).toContain('env(safe-area-inset-bottom, 0px)')
  })

  it('makes every destination thumb-sized and long labels able to wrap at 320px', () => {
    expect(shell).toContain('min-height: 72px;')
    expect(shell).toContain('grid-template-columns: 40px minmax(0, 1fr) 18px;')
    expect(shell).toContain('.qa-more-copy strong { font-size: 15px; line-height: 1.35; overflow-wrap: anywhere; }')
    expect(shell).toContain('.qa-more-copy small { font-size: 14px; line-height: 1.5; overflow-wrap: anywhere; }')
    expect(shell).toContain('.qa-more-note { font-size: 14px; line-height: 1.55; overflow-wrap: anywhere; }')
    expect(shell).toContain('background: var(--qa-more-surface);')
    expect(shell).toContain('--qa-more-surface: #f5f5ec;')
  })

  it('groups all six links in order under accessible headings with concise copy', () => {
    expect(shell).toContain('<h2 id="qa-more-title">More</h2>')
    expect(shell).toContain("{ id: 'home', label: 'Home & preferences', start: 0, end: 3 }")
    expect(shell).toContain("{ id: 'experiences', label: 'Other experiences', start: 3, end: 6 }")
    expect(shell).toContain('{#each MORE_GROUPS as group (group.id)}')
    expect(shell).toContain("aria-labelledby={'qa-more-group-' + group.id}")
    expect(shell).toContain("<h3 id={'qa-more-group-' + group.id}>{group.label}</h3>")
    expect(shell).toContain('{#each destinations.slice(group.start, group.end) as destination (destination.id)}')
    expect(shell).toContain('<small>{MORE_COPY[destination.id]}</small>')
    expect(shell).toContain('Preferences, history, and other experiences.')
    expect(shell).toContain('Apartment opens the current Home tools. The measured physical canvas is a separate, future page.')
    expect(shell).toContain('.qa-more-group h3 { margin: 0 0 10px; color: inherit; font-size: 14px;')
    expect(shell).toContain('color: #b1c0b3; font-size: 14px;')
    expect(shell).toContain('color: #9eafa1; font-size: 14px;')
    expect(shell).toContain('color: #91a294; font-size: 14px;')
  })

  it('compiles the original modal with its phone presentation changes without warnings', () => {
    const compiled = compile(shell, {
      filename: 'QuietAtlasShell.svelte',
      generate: 'dom',
      css: 'external',
    })
    expect(compiled.warnings).toEqual([])
  })
})
