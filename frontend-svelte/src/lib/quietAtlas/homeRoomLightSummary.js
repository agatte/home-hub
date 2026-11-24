import { sceneTemperatureColor, sceneCardBackground } from './sceneCards.js'
import { readStatus } from './lightSnapshot.js'

/**
 * Reported room lighting summary for Home. This is a UI projection of the
 * current light store, not a claim about physical bulb readback or room
 * presence. A missing/unreachable fixture is never counted as "off".
 *
 * @param {string[]} fixtureIds
 * @param {Record<string, { on?: boolean, reachable?: boolean }>} lightMap
 * @param {boolean} connected
 * @returns {{ label: string, tone: 'on'|'off'|'unknown'|'offline' }}
 */
export function homeRoomLightSummary(fixtureIds, lightMap, connected) {
  if (!connected) return { label: 'Disconnected', tone: 'offline' }
  if (!fixtureIds.length) return { label: 'No lights', tone: 'unknown' }

  const fixtures = fixtureIds.map((id) => lightMap[id])
  if (fixtures.some((light) => !light || typeof light.on !== 'boolean')) {
    return { label: 'Checking lights', tone: 'unknown' }
  }
  if (fixtures.some((light) => light.reachable !== true)) {
    return { label: 'Light unavailable', tone: 'unknown' }
  }

  const onCount = fixtures.filter((light) => light.on === true).length
  if (onCount === 0) return { label: 'All off', tone: 'off' }
  if (fixtureIds.length === 1) return { label: 'On', tone: 'on' }
  return {
    label: onCount === fixtureIds.length ? 'All on' : `${onCount} of ${fixtureIds.length} on`,
    tone: 'on',
  }
}

/** Reported room palette, not a physical color measurement or write target.
 * Require a complete reachable room report and known color/brightness for every on fixture.
 * @param {string[]} fixtureIds
 * @param {Record<string, {on?:boolean,reachable?:boolean,bri?:number,ct?:number,hue?:number,sat?:number,colormode?:string}>} lightMap
 * @param {boolean} connected
 * @returns {string}
 */
export function roomColorBackground(fixtureIds, lightMap, connected) {
  if (homeRoomLightSummary(fixtureIds, lightMap, connected).tone !== 'on') return ''
  const colors = []
  for (const id of fixtureIds) {
    const light = lightMap[id]
    if (!light.on) continue
    const { bri, ct, hue, sat, colormode } = light
    if (typeof bri !== 'number' || !Number.isFinite(bri) || bri < 1 || bri > 254) return ''
    const validCT = typeof ct === 'number' && Number.isFinite(ct) && ct >= 153 && ct <= 500
    const validHS = typeof hue === 'number' && Number.isFinite(hue) && hue >= 0 && hue <= 65535 &&
      typeof sat === 'number' && Number.isFinite(sat) && sat >= 0 && sat <= 254
    let color
    if (colormode === 'ct' && validCT) color = sceneTemperatureColor(ct)
    else if (colormode === 'hs' && validHS) color = `hsl(${hue / 65535 * 360}, ${sat / 254 * 100}%, 62%)`
    else return ''
    // Brightness modifies the displayed glow; preserve the reported chromaticity.
    colors.push(`color-mix(in srgb, ${color} ${Math.round(18 + bri / 254 * 82)}%, #141c19)`)
  }
  return sceneCardBackground([...new Set(colors)])
}

/** Home retains its live room labels and controls. A palette is shown only when
 * the recent independent REST snapshot agrees with those last reported values.
 * A changed live value immediately removes the old palette until the next read.
 * @param {string[]} fixtureIds
 * @param {import('./lightSnapshot.js').ReadOnlySnapshot} snapshot
 * @param {number} nowMs
 * @param {Record<string, import('./lightingModel.js').Fixture>} liveLights
 * @param {boolean} available
 */
export function homeSnapshotRoomColor(fixtureIds, snapshot, nowMs, liveLights, available) {
  if (!available || readStatus(snapshot, nowMs) !== 'recent-read') return ''
  const reported = roomColorBackground(fixtureIds, snapshot.fixtures, true)
  if (!reported || reported !== roomColorBackground(fixtureIds, liveLights, true)) return ''
  const snapshotSummary = homeRoomLightSummary(fixtureIds, snapshot.fixtures, true)
  const liveSummary = homeRoomLightSummary(fixtureIds, liveLights, true)
  return snapshotSummary.label === liveSummary.label ? reported : ''
}
