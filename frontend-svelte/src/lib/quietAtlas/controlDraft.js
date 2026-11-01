import { LIGHTING_GROUPS, normalizeSceneList, brightnessPercent } from './lightingModel.js'

// Drafts explain existing HomeHub command contracts; this module grants no
// write permission and performs no network or device actions.
const KNOWN_FIXTURES = new Set(LIGHTING_GROUPS.flatMap((group) => group.lightIds))

/** @param {ReturnType<import('./lightingModel.js').describeFixture>} fixture
 * @param {string} snapshotStatus */
export function canDraftBrightness(fixture, snapshotStatus) {
  return snapshotStatus === 'recent-read' &&
    !!fixture && KNOWN_FIXTURES.has(fixture.id) && fixture.known === true &&
    fixture.reachable === true && fixture.on === true &&
    typeof fixture.brightness === 'number' && Number.isInteger(fixture.brightness) &&
    fixture.brightness >= 1 && fixture.brightness <= 100
}

/** A proposed value, not a valid write authorization or telemetry attestation.
 * @param {ReturnType<import('./lightingModel.js').describeFixture>} fixture
 * @param {string} snapshotStatus
 * @param {unknown} proposedPercent */
export function reviewBrightnessDraft(fixture, snapshotStatus, proposedPercent) {
  if (!canDraftBrightness(fixture, snapshotStatus) ||
      typeof proposedPercent !== 'number' || !Number.isInteger(proposedPercent) ||
      proposedPercent < 1 || proposedPercent > 100 ||
      proposedPercent === fixture.brightness) return null
  return {
    fixtureId: fixture.id,
    name: fixture.name,
    fromPercent: fixture.brightness,
    toPercent: proposedPercent,
    // Existing PUT takes Hue's 1..254 bri domain, not 0..100 percentage.
    proposedBri: Math.max(1, Math.min(254, Math.round(proposedPercent * 254 / 100))),
    scope: 'single-fixture',
  }
}

/** The scene list includes configured targets for curated and custom scenes,
 * but these are *declarations*, never current bulb state or execution authority.
 * Malformed/partial data must be labelled unknown, not silently omitted.
 * @param {unknown} raw
 * @returns {Array<{id:string,label:string,power:string,brightness:string}> | null} */
export function declaredSceneTargets(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const states = /** @type {Record<string, any>} */ (raw).lights
  if (!states || typeof states !== 'object' || Array.isArray(states)) return null
  const ids = Object.keys(states)
  if (!ids.length || ids.length > 32 || ids.some((id) => !/^[1-9][0-9]{0,3}$/.test(id))) return null
  const rows = []
  for (const id of ids.sort((a, b) => Number(a) - Number(b))) {
    const state = states[id]
    if (!state || typeof state !== 'object' || Array.isArray(state) ||
        typeof state.on !== 'boolean') return null
    const percent = state.on && state.bri != null ? brightnessPercent(state.bri) : null
    if (state.on && state.bri != null && percent == null) return null
    rows.push({
      id,
      label: KNOWN_FIXTURES.has(id) ? `L${id}` : `Unmapped light ${id}`,
      power: state.on ? 'On' : 'Off',
      brightness: state.on ? (percent == null ? 'unspecified' : `${percent}%`) : 'not applicable',
    })
  }
  return rows
}

/** Scene listing metadata is not proof of actual device effects, readiness or permission.
 * @param {string | null} sceneId
 * @param {unknown} sceneList
 * @param {{connected:boolean,loading:boolean,error:string}} status */
export function reviewSceneDraft(sceneId, sceneList, status) {
  if (typeof sceneId !== 'string' || !status?.connected ||
      status.loading || status.error) return null
  const scene = normalizeSceneList(sceneList).find((item) => item.id === sceneId)
  if (!scene) return null
  const raw = Array.isArray(sceneList) ? sceneList.find((item) =>
    item?.id === scene.id && item?.source === scene.source) : null
  const declaredTargets = scene.source === 'bridge' ? null : declaredSceneTargets(raw)
  return {
    id: scene.id, name: scene.name, source: scene.source, declaredTargets,
    description: scene.source === 'bridge'
      ? 'A Hue bridge scene can affect multiple lights; its exact fixture manifest is not available from this list.'
      : declaredTargets
        ? `This ${scene.source === 'custom' ? 'custom scene' : 'HomeHub preset'} declares ${declaredTargets.length} fixture targets. Protected-light and effect handling may change the actual outcome.`
        : `This ${scene.source === 'custom' ? 'custom scene' : 'HomeHub preset'} did not provide a valid per-light declaration. Actual effect targets remain unknown.`,
  }
}
