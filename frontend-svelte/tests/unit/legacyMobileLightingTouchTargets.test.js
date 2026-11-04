import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import lightCard from '../../src/lib/components/LightCard.svelte?raw'
import sceneBrowser from '../../src/lib/components/SceneBrowser.svelte?raw'

describe('legacy Apartment mobile lighting touch targets (#461)', () => {
  it('keeps the independent light command and drag surfaces without nested buttons', () => {
    expect(lightCard).toContain('on:pointerdown|stopPropagation')
    expect(lightCard).toContain('on:click|stopPropagation={togglePower}')
    expect(lightCard).toContain("on:click|stopPropagation={() => { if (light.on) showPresets = !showPresets }}")
    expect(lightCard).toContain('class="chip-drag-surface"')
    expect(lightCard).toContain('linkedIds = []')
    expect(lightCard).toContain('function fanout(id, state)')
    expect(lightCard).not.toContain('.chip-power { width: 28px; height: 28px; }')
  })

  it('provides touch-sized power and swatch targets without enlarging the color dot', () => {
    expect(lightCard).toContain('@media (max-width: 760px)')
    expect(lightCard).toContain('style="background-color: {swatchColor}"')
    expect(lightCard).toContain('.chip-swatch:hover,')
    expect(lightCard).toContain('.light-off .chip-swatch {')
    expect(lightCard).toContain('width: 44px;')
    expect(lightCard).toContain('height: 44px;')
    expect(lightCard).toContain('border: 15px solid transparent;')
    expect(lightCard).toContain('background-clip: padding-box;')
    expect(lightCard).toContain('.chip-presets {')
    expect(lightCard).toContain('position: relative;')
    expect(lightCard).toContain('top: auto;')
    expect(lightCard).toContain('.preset-dots { flex-wrap: wrap; gap: 8px; }')
    expect(lightCard).toContain('.preset-tab { min-height: 44px; font-size: 12px; }')
    expect(lightCard).toContain('.chip-preset-dot { flex: 0 0 44px; width: 44px; height: 44px; }')
    expect(lightCard).toContain('.chip-power { width: 44px; height: 44px; }')
    expect(lightCard).toContain('.chip-swatch:focus-visible')
    expect(lightCard).toContain('.chip-power:focus-visible')
  })

  it('exposes finger-sized scene actions even when a device cannot hover', () => {
    expect(sceneBrowser).toContain('@media (max-width: 760px)')
    expect(sceneBrowser).toContain('grid-template-columns: minmax(0, 1fr)')
    expect(sceneBrowser).toContain('.scene-try-btn,')
    expect(sceneBrowser).toContain('.scene-edit-btn {')
    expect(sceneBrowser).toContain('position: static;')
    expect(sceneBrowser).toContain('flex: 0 0 44px;')
    expect(sceneBrowser).toContain('opacity: 1;')
    expect(sceneBrowser).toContain('min-height: 44px; font-size: 14px;')
    expect(sceneBrowser).toContain('.scene-try-btn:focus-visible')
    expect(sceneBrowser).toContain('.scene-edit-btn:focus-visible')
    expect(sceneBrowser).toContain('on:click|stopPropagation={() => { if (!tryItActive) onTryIt(scene.id, scene.display_name) }}')
    expect(sceneBrowser).toContain('on:click|stopPropagation={() => openEditEditor(scene)}')
    expect(sceneBrowser).toContain('on:click={() => activate(scene.id)}')
  })

  it('compiles the two existing actuator surfaces with no new Svelte warnings', () => {
    for (const [filename, source] of [['LightCard.svelte', lightCard], ['SceneBrowser.svelte', sceneBrowser]]) {
      expect(compile(source, { filename, generate: 'dom', css: 'external' }).warnings).toEqual([])
    }
  })
})