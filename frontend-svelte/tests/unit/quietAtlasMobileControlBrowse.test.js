import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import overview from '../../src/lib/components/QuietAtlasLightingOverview.svelte?raw'
import scenes from '../../src/lib/components/QuietAtlasSceneBrowser.svelte?raw'
import group from '../../src/lib/components/QuietAtlasGroupSheet.svelte?raw'

describe('Quiet Atlas phone-first read-only Control browse (#461)', () => {
  it('uses full-width, finger-sized room and scene targets on a phone', () => {
    expect(overview).toContain('@media(max-width:700px)')
    expect(overview).toContain('.groups,.scene-row { grid-template-columns:minmax(0,1fr); gap:9px; }')
    expect(overview).toContain('.group { box-sizing:border-box; min-height:76px;')
    expect(overview).toContain('.scene { box-sizing:border-box; min-height:68px;')
    expect(overview).toContain('.browse,.refresh-lights { min-height:44px; }')
    expect(overview).toContain('onOpenGroup(group.id)')
    expect(overview).toContain('onBrowseScenes')
    expect(overview).toContain('class="mobile-presets-shortcut" on:click={onBrowseScenes}')
    expect(overview).toContain('Review scenes · no activation')
    expect(overview).toContain('.mobile-presets-shortcut { box-sizing:border-box; display:flex;')
    expect(overview).toContain('min-height:64px;')
    expect(overview).toContain('onOpenScene(scene.id)')
    expect(overview).toContain('snapshotStatus === \'recent-read\'')
    expect(overview).toContain('Individual fixture freshness is unverified')
  })

  it('replaces horizontally scrolling scene filters with a native phone select', () => {
    expect(scenes).toContain('<label class="mobile-category-label" for="qa-scene-category">Scene category</label>')
    expect(scenes).toContain('<select id="qa-scene-category" class="mobile-category-select" bind:value={category}>')
    expect(scenes).toContain('{#each categories as cat (cat.id)}')
    expect(scenes).toContain('<option value={cat.id}>{cat.label}</option>')
    expect(scenes).toContain('on:click={() => category = cat.id}')
    expect(scenes).toContain("select:not(:disabled)")
    expect(scenes).toContain('.filter((element) => element instanceof HTMLElement)')
    expect(scenes).toContain('element.getClientRects().length > 0')
    expect(scenes).toContain('.filters { display:none; }')
    expect(scenes).toContain('.scene-grid { grid-template-columns:minmax(0,1fr); gap:10px; }')
    expect(scenes).toContain('.scene-review { min-height:48px; width:100%;')
    expect(scenes).toContain('filterScenes(sceneList, { category, search })')
    expect(scenes).toContain('role="dialog" aria-modal="true"')
    expect(scenes).toContain('Review preset impact')
    expect(scenes).toContain('No scene command has been sent.')
  })

  it('enlarges the local fixture draft without creating an Apply or broad group writer', () => {
    expect(group).toContain('.fixture input[type=range] { box-sizing:border-box; min-height:44px;')
    expect(group).toContain('.review,.dismiss-review { box-sizing:border-box; width:100%; min-height:48px;')
    expect(group).toContain('reviewBrightnessDraft')
    expect(group).toContain('Power, color and actual Apply are unavailable')
    expect(group).toContain('The grouping on Home does not create a new group command.')
    for (const surface of [overview, scenes, group]) {
      expect(surface).not.toMatch(/\b(apiPost|apiPut|setLight|activateScene|hueWrite|light_command)\s*\(/)
    }
  })

  it('compiles all three modified Svelte components without warnings', () => {
    for (const [filename, component] of [
      ['QuietAtlasLightingOverview.svelte', overview],
      ['QuietAtlasSceneBrowser.svelte', scenes],
      ['QuietAtlasGroupSheet.svelte', group],
    ]) {
      const result = compile(component, { filename, generate: 'dom', css: 'external' })
      expect(result.warnings, filename).toEqual([])
    }
  })
})
