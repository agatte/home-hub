import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { adaptSyntheticArtistReview431 as adapt } from '../../src/lib/appleMusicArtistReviewHandoff431.js'
const fixture = JSON.parse(readFileSync(new URL('../../src/lib/appleMusicArtistReviewHandoff431.fixture.json', import.meta.url), 'utf8'))
const copy = () => structuredClone(fixture)
test('projects bounded label/band pairs and distinct same-name claims without mutating input', () => {
  const input = copy(), before = copy(), result = adapt(input)
  assert.deepEqual(input, before)
  assert.deepEqual(result.fixtures, [[0], [1], [2, 3], [4]])
  assert.equal(result.candidates[2].name, result.candidates[3].name)
  assert.notEqual(result.candidates[2].note, result.candidates[3].note)
  assert.deepEqual(result.artists.map(a => a.days), ['10+ example days', '4–9 example days', '2–3 example days', '1 example day'])
  assert.ok(Object.isFrozen(result.artists[0]))
  assert.ok(Object.isFrozen(result.fixtures[2]))
  input.artists[0].label = 'Fictional Changed Label'
  assert.equal(result.artists[0].name, fixture.artists[0].label)
})
const cases = {
  provenance: p => { p.provenance = 'local_reviewer' },
  source: p => { p.source = 'other' },
  evidence: p => { p.evidence = 'plays' },
  identity: p => { p.identity_status = 'verified' },
  schema: p => { p.schema = 1 },
  unsupportedBand: p => { p.artists[0].date_band = '11' },
  inconsistentBand: p => { p.artists[0].date_band = '1' },
  duplicate: p => { p.artists[1] = structuredClone(p.artists[0]) },
  oversized: p => { p.artists.push(structuredClone(p.artists[0])) },
  missing: p => { p.candidates.pop() },
  nested: p => { p.artists[0].extra = { private: 'Fictional Only' } },
  unknownRef: p => { p.artists[0].candidate_refs[0] = 'demo-99' },
  conflict: p => { p.candidates[3].ref = 'demo-3' },
  provider: p => { p.candidates[0].provider = 'Fictional Other Service' },
  claim: p => { p.candidates[0].note = 'Fictional Changed Claim' },
  realMarker: p => { p.real_data = false },
  csvShape: p => { p.artists[0] = ['Fictional Only', '1'] },
  prototype: p => { Object.setPrototypeOf(p.artists[0], { hidden: true }) },
  accessor: p => { Object.defineProperty(p.artists[0], 'label', { get() { throw Error('must not read') } }) },
}
for (const flag of Object.keys(fixture).filter(k => fixture[k] === false)) cases[flag] = p => { p[flag] = true }
for (const label of ['', 'Fictional Changed Label', 'Imaginary Atlas Ensemble\n', 'Imaginary\u202e Atlas Ensemble', '<b>Invented Sound Group</b>', ' Imaginary Atlas Ensemble', 'Imaginary Atlas Ensemble'.repeat(1000)]) {
  cases[`label-${Object.keys(cases).length}`] = p => { p.artists[0].label = label }
}
for (const [name, mutate] of Object.entries(cases)) test(`fails closed: ${name}`, () => {
  const input = copy(); mutate(input)
  assert.throws(() => adapt(input), { message: 'Invalid synthetic artist review fixture.' })
})
for (const input of [null, [], 'Fictional CSV', {}, 1]) test(`rejects nonpacket ${typeof input}`, () => {
  assert.throws(() => adapt(input), { message: 'Invalid synthetic artist review fixture.' })
})
test('hostile traps fail with fixed redacted error only', () => {
  const syntheticTrap = () => { throw new Error('SYNTHETIC_PRIVATE_VALUE') }
  const topLevel = new Proxy({}, { getPrototypeOf: syntheticTrap })
  const nested = copy()
  nested.artists[0] = new Proxy(nested.artists[0], { ownKeys: syntheticTrap })
  for (const packet of [topLevel, nested]) {
    assert.throws(() => adapt(packet), {
      message: 'Invalid synthetic artist review fixture.',
    })
  }
})

test('route has only static fixture ingress; adapter has no IO or value logging', () => {
  const route = readFileSync(new URL('../../src/routes/quiet-atlas/music/artist-review/+page.svelte', import.meta.url), 'utf8')
  const adapter = readFileSync(new URL('../../src/lib/appleMusicArtistReviewHandoff431.js', import.meta.url), 'utf8')
  assert.match(route, /adaptSyntheticArtistReview431\(packet\)/)
  assert.match(route, /import packet from '\$lib\/appleMusicArtistReviewHandoff431.fixture.json'/)
  for (const source of [route, adapter]) {
    assert.doesNotMatch(source, /\b(fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon|apiGet|apiPost|import)\s*\(/)
    assert.doesNotMatch(source, /\b(localStorage|sessionStorage|indexedDB|clipboard|URLSearchParams|FileReader|console)\b|\$page|type=["']file/)
  }
})
