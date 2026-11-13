import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  shouldUseQuietAtlasShell, activeQuietAtlasSection,
  shouldShowGlobalErrorToast, MORE_DESTINATIONS,
} from '../../src/lib/quietAtlas/navigation.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('root uses redesigned Home with fully preserved classic dashboard', () => {
  const root = read('../../src/routes/+page.svelte')
  const classic = read('../../src/routes/classic/+page.svelte')
  assert.match(root, /import RedesignedHome/)
  assert.match(root, /<RedesignedHome \/>/)
  assert.match(classic, /id="apartment-controls"/)
  assert.match(classic, /<ApartmentWidget \/>/)
  assert.equal(shouldUseQuietAtlasShell('/', new URLSearchParams()), true)
  assert.equal(shouldUseQuietAtlasShell('/classic', new URLSearchParams('shell=quiet-atlas')), false)
  assert.equal(activeQuietAtlasSection('/'), 'home')
  assert.equal(shouldShowGlobalErrorToast('/', new URLSearchParams()), true)
  assert.equal(MORE_DESTINATIONS.find(x => x.id === 'apartment').href, '/classic')
})

test('in-flow reveal controls L1–L6 individually, not fake preview values', () => {
  const controls = read('../../src/lib/components/QuietAtlasRoomControls.svelte')
  const reveal = read('../../src/lib/components/QuietAtlasHomeLightingReveal.svelte')
  const home = read('../../src/routes/quiet-atlas/home/+page.svelte')
  assert.match(reveal, /<QuietAtlasRoomControls room=\{group.id\}/)
  assert.doesNotMatch(reveal, /Preview glow|Preview power|<QuietAtlasInlineFixtures/)
  assert.match(controls, /import LightCard from/)
  assert.match(controls, /<LightCard light=\{\$lights\[lightId\]\} optimisticStore=\{false\} \/>/)
  for (const map of ["living: ['1']", "bedroom: ['2', '5']", "kitchen: ['3', '4']", "plant: ['6']"])
    assert.ok(controls.includes(map), map)
  assert.doesNotMatch(controls, /linkedIds=|<LightGrid|apiPut|fetch\(/)
  assert.match(controls, /!\$connected/)
  assert.match(controls, /reachable === true/)
  assert.match(home, /href="#phone-lighting-title"/)
  assert.match(home, /href="#lighting-title"/)
  assert.match(home, /href="\/classic"/)
})

test('kiosk default URL needs no startup change and fallback is alive', () => {
  const kiosk = read('../../../scripts/recycle-kiosk.sh')
  const shell = read('../../src/lib/components/QuietAtlasShell.svelte')
  const detail = read('../../src/routes/quiet-atlas/lighting/[groupId]/+page.svelte')
  const control = read('../../src/routes/quiet-atlas/control/+page.svelte')
  assert.ok(kiosk.includes('localhost:8000'))
  assert.doesNotMatch(kiosk, /quiet-atlas/)
  assert.match(shell, /id: 'home', label: 'Home', href: '\/'/)
  assert.match(detail, /href="\/classic#apartment-controls"/)
  assert.match(control, /href="\/classic#apartment-controls"/)
})
