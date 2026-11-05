import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import source from '../../src/lib/components/ModeCardDeck.svelte?raw'

describe('phone functional mode handoff is discoverable (#461)', () => {
  it('shows all nine choices in a non-scrolling phone grid', () => {
    expect(source).toMatch(/@media \(max-width: 600px\)\s*\{[\s\S]*?grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)/)
    expect(source).not.toMatch(/overflow-x:\s*auto/)
    expect(source).not.toMatch(/scrollbar-width:\s*none/)
    expect(source).toMatch(/\.mode-card-danger\s*\{\s*grid-column:\s*1\s*\/\s*-1;/)
    expect(source).toMatch(/\.mode-card\s*\{[^}]*min-height:\s*64px;/s)
  })

  it('places the distinct All Off action after activity choices in DOM and focus order', () => {
    expect(source.indexOf("{ id: 'alloff'")).toBeGreaterThan(source.indexOf("{ id: 'auto'"))
    expect(source).toContain("aria-label={card.isAction ? 'Turn all lights off' : `${card.label} mode`}")
    expect(source).toContain('aria-pressed={activeMap[card.id]}')
  })

  it('does not modify existing light and activity command handlers', () => {
    expect(source).toContain("await apiPost('/api/lights/all', { on: false })")
    expect(source).toContain('await setManualMode(card.id)')
    expect(source).toContain('on:click={() => handleClick(card)}')
  })

  it('compiles without introducing Svelte warnings', () => {
    expect(compile(source, { filename: 'ModeCardDeck.svelte', generate: 'dom', css: 'external' }).warnings).toEqual([])
  })
})
