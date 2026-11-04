/**
 * #431 fixtures-only seam for the local reviewer's (unverified label, date-band)
 * shape. This is deliberately NOT an adapter for that reviewer's real RAM data.
 * No IO, telemetry, normalization, identity proof or authority promotion.
 */
const labels = Object.freeze([
  'Imaginary Atlas Ensemble', 'Fictional Pattern Unit',
  'Invented Sound Group', 'Makebelieve Echo Collective',
])
const bands = Object.freeze(['10+', '4-9', '2-3', '1'])
const days = Object.freeze(['10+ example days', '4–9 example days', '2–3 example days', '1 example day'])
const notes = Object.freeze([
  'Invented lunar chamber ensemble', 'Invented geometric percussion group',
  'Invented paper instrument quartet', 'Invented cloud instrument duo — distinct candidate',
  'Invented silent theatre ensemble',
])
const owners = Object.freeze([0, 1, 2, 2, 3])
const references = Object.freeze([['demo-1'], ['demo-2'], ['demo-3', 'demo-4'], ['demo-5']])
const policy = Object.freeze({
  schema: 'artist_review_fixture_431_v1', provenance: 'synthetic_fixture_only',
  source: 'apple_daily_tracks', evidence: 'artist_label_day_exposure', identity_status: 'unverified',
  preference_eligible: false, session_proven: false, cross_source_independent: false,
  actuation_eligible: false, live_catalog_enabled: false, network_enabled: false,
  persistence_enabled: false,
})
function invalid() { throw new Error('Invalid synthetic artist review fixture.') }

// Exact own data properties only: reject nested extras, prototypes and accessors
// without reading their values. No input values enter errors or logs.
function record(value, keys) {
  if (!value || Object.getPrototypeOf(value) !== Object.prototype) invalid()
  const descriptors = Object.getOwnPropertyDescriptors(value)
  const actual = Reflect.ownKeys(descriptors)
  if (actual.length !== keys.length || actual.some(key => !keys.includes(key))) invalid()
  for (const key of keys) {
    if (!descriptors[key] || !('value' in descriptors[key]) || !descriptors[key].enumerable) invalid()
  }
}
function list(value, length) {
  if (!Array.isArray(value) || Object.getPrototypeOf(value) !== Array.prototype || value.length !== length) invalid()
  const keys = Array.from({ length }, (_, i) => String(i))
  const descriptors = Object.getOwnPropertyDescriptors(value)
  if (Reflect.ownKeys(descriptors).length !== length + 1) invalid()
  for (const key of keys) if (!descriptors[key] || !('value' in descriptors[key])) invalid()
}
/**
 * Validate the entire bounded packet before returning an immutable UI projection.
 * Fixed vocabulary and fixed claim refs are intentional: a synthetic provenance
 * string cannot authorize new labels, real catalog IDs or altered date evidence.
 * @param {unknown} input
 * @returns {{artists: ReadonlyArray<{name: string, days: string}>, candidates: ReadonlyArray<{name: string, note: string}>, fixtures: ReadonlyArray<ReadonlyArray<number>>}}
 */
export function adaptSyntheticArtistReview431(input) {
  // Even hostile proxy traps must not put user-controlled values into errors.
  try { return adaptFixturePacket(input) } catch {
    // Explicit throw is required for Svelte's checked-JS return typing.
    throw new Error('Invalid synthetic artist review fixture.')
  }
}

/** @param {unknown} input */
function adaptFixturePacket(input) {
  // The validator narrows unknown structurally at runtime; no caller trust.
  const packet = /** @type {any} */ (input)
  record(packet, [...Object.keys(policy), 'artists', 'candidates'])
  for (const [key, value] of Object.entries(policy)) if (packet[key] !== value) invalid()
  list(packet.artists, 4)
  list(packet.candidates, 5)
  packet.artists.forEach((row, i) => {
    record(row, ['ref', 'label', 'date_band', 'candidate_refs'])
    if (row.ref !== `fixture-label-${i + 1}` || row.label !== labels[i] || row.date_band !== bands[i]) invalid()
    list(row.candidate_refs, references[i].length)
    row.candidate_refs.forEach((ref, j) => { if (ref !== references[i][j]) invalid() })
  })
  packet.candidates.forEach((claim, i) => {
    record(claim, ['ref', 'provider', 'name', 'note'])
    if (claim.ref !== `demo-${i + 1}` || claim.provider !== 'DemoCatalog' ||
        claim.name !== labels[owners[i]] || claim.note !== notes[i]) invalid()
  })
  return Object.freeze({
    artists: Object.freeze(packet.artists.map(row => Object.freeze({ name: row.label, days: days[bands.indexOf(row.date_band)] }))),
    candidates: Object.freeze(packet.candidates.map(claim => Object.freeze({ name: claim.name, note: claim.note }))),
    fixtures: Object.freeze(packet.artists.map(row => Object.freeze(row.candidate_refs.map(ref => packet.candidates.findIndex(claim => claim.ref === ref))))),
  })
}
