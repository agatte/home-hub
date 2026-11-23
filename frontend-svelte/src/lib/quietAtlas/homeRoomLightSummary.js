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
