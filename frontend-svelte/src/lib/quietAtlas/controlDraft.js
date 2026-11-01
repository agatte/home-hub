import { LIGHTING_GROUPS, normalizeSceneList } from './lightingModel.js'

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

/** Scene listing metadata is not an effect manifest, readiness or permission.
 * @param {string | null} sceneId
 * @param {unknown} sceneList
 * @param {{connected:boolean,loading:boolean,error:string}} status */
export function reviewSceneDraft(sceneId, sceneList, status) {
  if (typeof sceneId !== 'string' || !status?.connected ||
      status.loading || status.error) return null
  const scene = normalizeSceneList(sceneList).find((item) => item.id === sceneId)
  if (!scene) return null
  return {
    id: scene.id, name: scene.name, source: scene.source,
    description: scene.source === 'bridge'
      ? 'A Hue bridge scene can affect multiple lights; its exact fixture manifest is not available from this list.'
      : scene.source === 'custom'
        ? 'A saved custom scene can affect multiple fixtures; this list does not verify its current targets.'
        : 'A curated HomeHub scene can affect multiple fixtures and existing manual lighting ownership.',
  }
}
