/**
 * Quiet Atlas / #270 lighting presentation selectors. No device writes.
 * A visual room grouping does NOT confer room-wide actuation authority.
 */

/** @typedef {{light_id?: string, name?: string, on?: boolean, reachable?: boolean, bri?: number, ct?: number, hue?: number, sat?: number, colormode?: string}} Fixture */
export const LIGHTING_GROUPS = Object.freeze([
  { id: 'living', label: 'Living room', lightIds: ['1'] },
  { id: 'bedroom', label: 'Bedroom', lightIds: ['2', '5'] },
  { id: 'kitchen', label: 'Kitchen', lightIds: ['3', '4'] },
  { id: 'plant', label: 'Plant Wash', lightIds: ['6'] },
]);

/** The existing Hue bridge's brightness domain is 1..254. */
export function brightnessPercent(raw) {
  if (typeof raw !== 'number' || !Number.isFinite(raw) || raw < 1 || raw > 254) return null;
  return Math.round((raw / 254) * 100);
}

/**
 * @param {Fixture | undefined} light
 * @param {string} id
 * @returns {{id: string, name: string, known: boolean, reachable: boolean | null, on: boolean | null, brightness: number | null, colorMode: string | null}}
 */
export function describeFixture(light, id) {
  const known = !!light && typeof light === 'object' && !Array.isArray(light);
  // Missing fields are UNKNOWN, distinct from a confirmed unreachable light.
  const reachable = known && typeof light?.reachable === 'boolean' ? light.reachable : null;
  const on = reachable === true && typeof light?.on === 'boolean' ? light.on : null;
  return {
    id,
    name: known && typeof light?.name === 'string' && light.name.trim() ? light.name.trim() : `Light ${id}`,
    known,
    reachable,
    on,
    brightness: on === true ? brightnessPercent(light?.bri) : null,
    colorMode: reachable === true && typeof light?.colormode === 'string' ? light.colormode : null,
  };
}

/** @param {ReturnType<typeof describeFixture>[]} fixtures */
export function summarizeFixtureGroup(fixtures) {
  if (!fixtures.length || fixtures.every((f) => !f.known || f.reachable === null)) return 'unknown';
  if (fixtures.every((f) => f.known && f.reachable === false)) return 'offline';
  if (fixtures.some((f) => !f.known || f.reachable !== true || f.on === null)) return 'partial';
  const lit = fixtures.filter((f) => f.on === true).length;
  return lit === fixtures.length ? 'on' : lit === 0 ? 'off' : 'mixed';
}

/**
 * @param {Record<string, Fixture> | null | undefined} lightsMap
 * @param {boolean} connected Whether a current HomeHub connection is established.
 */
export function buildLightingOverview(lightsMap, connected = true) {
  const source = lightsMap && typeof lightsMap === 'object' && !Array.isArray(lightsMap) ? lightsMap : {};
  const knownIds = new Set(LIGHTING_GROUPS.flatMap((g) => g.lightIds));
  const make = (g, fixtures) => ({
    id: g.id, label: g.label, fixtureIds: fixtures.map((f) => f.id), fixtures,
    status: connected ? summarizeFixtureGroup(fixtures) : 'stale',
    onCount: fixtures.filter((f) => f.on === true).length,
    total: fixtures.length,
    // Even the Kitchen pair is ONLY a visual group (custom scenes can diverge).
    supportsGroupWrite: false,
  });
  const groups = LIGHTING_GROUPS.map((g) => make(g, g.lightIds.map((id) => describeFixture(source[id], id))));
  const extras = Object.keys(source)
    .filter((id) => !knownIds.has(id))
    .sort((a, b) => a.localeCompare(b, 'en', { numeric: true }))
    .map((id) => describeFixture(source[id], id));
  if (extras.length) groups.push(make({ id: 'other', label: 'Other lights' }, extras));
  return groups;
}

/** @param {unknown} input */
export function normalizeSceneList(input) {
  const scenes = Array.isArray(input) ? input : [];
  const seen = new Set();
  return scenes.flatMap((s) => {
    if (!s || typeof s !== 'object' || !['preset', 'custom', 'bridge'].includes(s.source)) return [];
    if (typeof s.id !== 'string' || !s.id.trim() || seen.has(s.id)) return [];
    const label = s.display_name || s.name;
    if (typeof label !== 'string' || !label.trim()) return [];
    seen.add(s.id);
    return [{ id: s.id, name: label.trim(), source: s.source,
      category: typeof s.category === 'string' && s.category.trim() ? s.category : null }];
  });
}

/** Proposed quick choices are selected ONLY from the response, not invented. */
export function selectQuickScenes(input, favoriteIds = [], max = 4) {
  const scenes = normalizeSceneList(input);
  if (!Number.isInteger(max) || max <= 0) return [];
  if (Array.isArray(favoriteIds) && favoriteIds.length) {
    const byId = new Map(scenes.map((s) => [s.id, s]));
    return [...new Set(favoriteIds)].flatMap((id) => {
      const scene = byId.get(id);
      return scene ? [scene] : [];
    }).slice(0, max);
  }
  const defaults = ['Golden Hour', 'Ember', 'Deep Focus', 'Movie Night'];
  return defaults.flatMap((name) => {
    const scene = scenes.find((s) => s.source === 'preset' && s.name === name);
    return scene ? [scene] : [];
  }).slice(0, max);
}

/** Pure scene filtering for the separate browse sheet (no automatic activation). */
export function filterScenes(input, { category = 'all', search = '' } = {}) {
  const term = typeof search === 'string' ? search.trim().toLocaleLowerCase() : '';
  return normalizeSceneList(input).filter((s) => {
    if (category !== 'all' && category !== s.category && category !== s.source) return false;
    return !term || s.name.toLocaleLowerCase().includes(term);
  });
}

/** @param {ReturnType<typeof describeFixture>} f */
export function fixtureStatusLabel(f) {
  if (!f.known || f.reachable === null) return 'Unknown';
  if (f.reachable === false) return 'Offline';
  if (f.on === null) return 'State unavailable';
  if (!f.on) return 'Off';
  return f.brightness === null ? 'On · brightness unknown' : `On · ${f.brightness}%`;
}
