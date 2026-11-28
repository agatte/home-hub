import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  shouldUseQuietAtlasShell, activeQuietAtlasSection,
  shouldShowGlobalErrorToast, MORE_DESTINATIONS, classicBookmarkHref,
} from '../../src/lib/quietAtlas/navigation.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('root uses redesigned Home with a redirect-only Classic bookmark', () => {
  const root = read('../../src/routes/+page.svelte')
  const classic = read('../../src/routes/classic/+page.svelte')
  assert.match(root, /import RedesignedHome/)
  assert.match(root, /<RedesignedHome \/>/)
  assert.match(classic, /goto\(destination, \{ replaceState: true \}\)/)
  assert.doesNotMatch(classic, /<ApartmentWidget|<ModeCardDeck|<SonosCard/)
  assert.equal(classicBookmarkHref('#apartment-controls'), '/quiet-atlas/control')
  assert.equal(classicBookmarkHref('#https://example.com'), '/')
  assert.equal(shouldUseQuietAtlasShell('/', new URLSearchParams()), true)
  assert.equal(shouldUseQuietAtlasShell('/classic', new URLSearchParams('shell=quiet-atlas')), true)
  assert.equal(activeQuietAtlasSection('/'), 'home')
  assert.equal(shouldShowGlobalErrorToast('/', new URLSearchParams()), true)
  assert.equal(MORE_DESTINATIONS.find(x => x.id === 'apartment').href, '/quiet-atlas/household')
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
  assert.equal((controls.match(/linkedIds=/g) ?? []).length, 1)
  assert.ok(controls.includes("light={$lights['3']} linkedIds={['4']}"))
  assert.ok(controls.includes('writeAllowed={linkedCanWrite}'))
  assert.doesNotMatch(controls, /<LightGrid|apiPut|fetch\(/)
  assert.match(controls, /!\$connected/)
  assert.match(controls, /\$deviceStatus\.light_command_results !== true/)
  assert.match(controls, /reachable === true/)
  assert.match(home, /id="phone-lighting-title"/)
  assert.match(home, /id="lighting-title"/)
  assert.ok(home.includes('href="/quiet-atlas/household"'))
  assert.ok(!home.includes('href="/classic"'))
})

test('kiosk default URL needs no startup change and Control remains functional', () => {
  const kiosk = read('../../../scripts/recycle-kiosk.sh')
  const shell = read('../../src/lib/components/QuietAtlasShell.svelte')
  const detail = read('../../src/routes/quiet-atlas/lighting/[groupId]/+page.svelte')
  const control = read('../../src/routes/quiet-atlas/control/+page.svelte')
  assert.ok(kiosk.includes('localhost:8000'))
  assert.doesNotMatch(kiosk, /quiet-atlas/)
  assert.match(shell, /id: 'home', label: 'Home', href: '\/'/)
  assert.doesNotMatch(detail, /href="\/classic#apartment-controls"/)
  assert.match(detail, /These lights are not configured for HomeHub control/)
  assert.match(control, /<QuietAtlasLightingExperience \{routeIntent\} functional=\{true\} \/>/)
  assert.doesNotMatch(control, /href="\/classic#apartment-controls"/)
})
