import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { rootRuntimeTargets } from '../../src/lib/quietAtlas/runtimeRoutePolicy431.js'

const PREVIEW = '/quiet-atlas/music/artist-review'

test('direct artist-review entry never starts HomeHub general or Game Day runtime', () => {
  assert.deepEqual(rootRuntimeTargets(PREVIEW), { general: false, gameday: false })
  assert.deepEqual(rootRuntimeTargets('/guest'), { general: false, gameday: false })
  assert.deepEqual(rootRuntimeTargets('/guest/wifi'), { general: false, gameday: false })
  assert.deepEqual(rootRuntimeTargets('/gameday/prototype'), { general: false, gameday: true })
})

test('normal Music and other functional pages keep existing runtime', () => {
  for (const path of ['/', '/quiet-atlas/music', '/quiet-atlas/control',
    '/music', '/gameday', '/quiet-atlas/home']) {
    assert.equal(rootRuntimeTargets(path).general, true, path)
  }
  assert.deepEqual(rootRuntimeTargets('/gameday'), { general: true, gameday: true })
  assert.deepEqual(rootRuntimeTargets('/quiet-atlas/music'), { general: true, gameday: false })
})

test('client navigation in and out of preview stops and resumes exactly one runtime', () => {
  const events = []
  let general = false, gameday = false
  function change(path) {
    const target = rootRuntimeTargets(path)
    if (target.gameday && !gameday) { gameday = true; events.push('startGameday') }
    if (!target.gameday && gameday) { gameday = false; events.push('stopGameday') }
    if (target.general && !general) { general = true; events.push('startGeneral') }
    if (!target.general && general) { general = false; events.push('stopGeneral') }
  }
  change(PREVIEW)
  assert.deepEqual(events, [])
  change('/quiet-atlas/music')
  change(PREVIEW)
  change(PREVIEW)
  change('/gameday')
  change(PREVIEW)
  change('/quiet-atlas/control')
  assert.deepEqual(events, [
    'startGeneral', 'stopGeneral',
    'startGameday', 'startGeneral',
    'stopGameday', 'stopGeneral',
    'startGeneral',
  ])
  assert.equal(general, true)
  assert.equal(gameday, false)
})

test('root layout wires SvelteKit page subscription through runtime targets and cleanup', () => {
  const layout = readFileSync(new URL('../../src/routes/+layout.svelte', import.meta.url), 'utf8')
  assert.match(layout, /import \{ rootRuntimeTargets \} from '\$lib\/quietAtlas\/runtimeRoutePolicy431\.js'/)
  assert.match(layout, /page\.subscribe\(\(\$page\) => \{/)
  assert.match(layout, /rootRuntimeTargets\(\$page\.url\.pathname\)/)
  assert.match(layout, /if \(general\) startGeneral\(\)/)
  assert.match(layout, /else stopGeneral\(\)/)
  assert.match(layout, /if \(gameday\)[\s\S]*?initGamedayFeed\(\)/)
  assert.match(layout, /else stopGameday\(\)/)
  assert.match(layout, /return \(\) => \{ unsubscribe\(\); stopGeneral\(\); stopGameday\(\) \}/)
})
