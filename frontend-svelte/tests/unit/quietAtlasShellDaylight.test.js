import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import shellSource from '../../src/lib/components/QuietAtlasShell.svelte?raw'

describe('Quiet Atlas Home Daylight shell preview contract', () => {
  it('compiles a scoped optional Daylight treatment for navigation and More', () => {
    const output = compile(shellSource, {
      filename: 'QuietAtlasShell.svelte',
      generate: 'dom',
      css: 'external',
    })
    expect(output.warnings).toEqual([])
    const css = output.css?.code ?? ''
    // Svelte must compile away :global(). A literal :global() inside :has()
    // was an observed non-matching selector in the mounted Edge browser.
    expect(css).toContain('.qa-shell:has(.home-review.daylight)')
    expect(css).not.toContain(':global(')
    for (const selector of ['.qa-sidebar', '.qa-mobile-header', '.qa-mobile-nav', '.qa-more-panel']) {
      expect(css).toContain(selector)
    }
    // The user-controlled Home preview is deliberately not a persisted,
    // inferred, global or automatic ambient theme.
    expect(shellSource).not.toMatch(/localStorage|matchMedia.*prefers-color-scheme/)
    expect(shellSource).toContain('Preview-only Daylight coordination')
  })
})
