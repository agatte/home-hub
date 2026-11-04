import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import lightCard from '../../src/lib/components/LightCard.svelte?raw'

describe('legacy desktop color presets stay within the light card (#461)', () => {
  it('keeps the preset panel in flow, including desktop widths', () => {
    expect(lightCard).toMatch(/\.chip-presets\s*\{[^}]*position:\s*relative;[^}]*top:\s*auto;[^}]*width:\s*max-content;[^}]*max-width:\s*100%;/s)
    expect(lightCard).toContain('overflow: hidden;')
    expect(lightCard).not.toMatch(/\.chip-presets\s*\{[^}]*top:\s*100%;/s)
  })

  it('preserves brightness drag and light command contracts', () => {
    expect(lightCard).toContain('on:pointerdown={onPointerDown}')
    expect(lightCard).toContain('on:click|stopPropagation={togglePower}')
    expect(lightCard).toContain('function setColor(hue, sat)')
    expect(lightCard).toContain('function setCT(ct)')
    expect(lightCard).toContain('function fanout(id, state)')
  })

  it('compiles without new Svelte warnings', () => {
    expect(compile(lightCard, { filename: 'LightCard.svelte', generate: 'dom', css: 'external' }).warnings).toEqual([])
  })
})