import { describe, expect, it } from 'vitest'
import { compile } from 'svelte/compiler'
import home from '../../src/routes/quiet-atlas/home/+page.svelte?raw'
import panel from '../../src/lib/components/QuietAtlasHomeModeControls.svelte?raw'
import classic from '../../src/routes/classic/+page.svelte?raw'
import storeActions from '../../src/lib/stores/init.js?raw'

describe('#461 redesigned Home mode recovery', () => {
  it('restores mode controls to default Home without replacing the functional Classic fallback', () => {
    expect(home).toContain("import QuietAtlasHomeModeControls from '$lib/components/QuietAtlasHomeModeControls.svelte'")
    expect(home).toContain('<QuietAtlasHomeModeControls />')
    expect(classic).toContain('<ModeCardDeck />')
  })

  it('offers Auto and every existing manual mode through the established authenticated endpoint', () => {
    expect(panel).toContain("import { setManualMode } from '$lib/stores/init.js'")
    expect(panel).toContain("requestMode('auto')")
    expect(panel).toContain('setManualMode(mode)')
    for (const [mode, label] of [
      ['relax', 'Relax'], ['working', 'Working'], ['watching', 'Watching'],
      ['gaming', 'Gaming'], ['cooking', 'Cooking'], ['social', 'Party'],
      ['sleeping', 'Sleep'],
    ]) {
      expect(panel).toContain("{ id: '" + mode + "', label: '" + label + "' }")
    }
    expect(storeActions).toContain("apiPost('/api/automation/override', { mode })")
    expect(panel).not.toContain('setLight(')
    expect(panel).not.toContain('light_command')
  })

  it('fails closed without connected house state and requires explicit confirmation from Away or Sleeping', () => {
    expect(panel).toContain("$connected && KNOWN_HOUSE_STATES.includes($automation.house_state)")
    expect(panel).toContain("const sensitiveAction = $automation.house_state === 'sleeping' || $automation.house_state === 'away'")
    expect(panel).toContain('sensitiveAction && armedMode !== mode')
    expect(panel).toContain('armedMode = null')
    expect(panel).toContain('disabled={!canChange || pending}')
    expect(panel).toContain('disabled={!canChange || pending || !selectedMode}')
    expect(panel).toContain('Mode result uncertain.')
    expect(panel).not.toContain('window.confirm(')
  })

  it('compiles without Svelte accessibility warnings', () => {
    expect(compile(panel, {
      filename: 'QuietAtlasHomeModeControls.svelte', generate: 'dom', css: 'external',
    }).warnings).toEqual([])
  })
})
