// Sector Board geometry — deterministic 8-wedge layout, no physics.
// Sectors are 45° wide, starting at 12 o'clock and going clockwise.

export const SECTOR_COUNT = 8
export const SECTOR_ARC = (Math.PI * 2) / SECTOR_COUNT // 45°

// Wedge ordering (sector index → input id). Behavioral signals live on the
// top half (you "drive" the system), lights are the bottom output, context
// fills the left half.
export const SECTORS = [
  { id: 'process', label: 'Process', icon: 'cpu',     kind: 'voter' },
  { id: 'camera',  label: 'Camera',  icon: 'video',   kind: 'voter' },
  { id: 'audio',   label: 'Audio',   icon: 'mic',     kind: 'voter' },
  { id: 'rules',   label: 'Rules',   icon: 'clock',   kind: 'voter' },
  { id: 'lights',  label: 'Lights',  icon: 'lightbulb', kind: 'output' },
  { id: 'sonos',   label: 'Sonos',   icon: 'music',   kind: 'context' },
  { id: 'weather', label: 'Weather', icon: 'cloud',   kind: 'context' },
  { id: 'time',    label: 'Time',    icon: 'sun',     kind: 'context' },
]

// Map id → sector index for the rare lookup.
export const SECTOR_INDEX = SECTORS.reduce((acc, s, i) => {
  acc[s.id] = i
  return acc
}, /** @type {Record<string, number>} */ ({}))

/** Sector mid-angle in radians. Sector 0 centered at 12:00 (clock), going clockwise. */
export function sectorMidAngle(i) {
  return -Math.PI / 2 + (i + 0.5) * SECTOR_ARC
}

/** Sector start/end angles (radians), useful for clip-path / boundary lines. */
export function sectorBounds(i) {
  const start = -Math.PI / 2 + i * SECTOR_ARC
  return { start, end: start + SECTOR_ARC, mid: start + SECTOR_ARC / 2 }
}

/**
 * Position the input bubble for a sector.
 * @param {number} i sector index
 * @param {number} cx canvas center x
 * @param {number} cy canvas center y
 * @param {number} R inner-bubble radius (distance from center)
 */
export function inputBubblePosition(i, cx, cy, R) {
  const a = sectorMidAngle(i)
  return { x: cx + Math.cos(a) * R, y: cy + Math.sin(a) * R }
}

/**
 * Position sub-bubbles in a sector. Spread radially+angularly around the input
 * bubble so they never escape the sector wedge.
 *
 * @param {number} i sector index
 * @param {number} cx canvas center x
 * @param {number} cy canvas center y
 * @param {number} R_input radial distance of the input bubble from center
 * @param {number} R_sub radial distance of sub-bubbles from center (slightly outside input bubble)
 * @param {number} count number of sub-bubbles to place (0..4)
 */
export function subBubblePositions(i, cx, cy, R_input, R_sub, count) {
  if (count <= 0) return []
  const mid = sectorMidAngle(i)
  // Spread within ~30° of the mid-angle (sector is 45° wide, so 7.5° padding each side).
  const spreadDeg = 30
  const spread = (spreadDeg * Math.PI) / 180
  /** @type {{x: number, y: number, angle: number}[]} */
  const out = []
  if (count === 1) {
    out.push({ x: cx + Math.cos(mid) * R_sub, y: cy + Math.sin(mid) * R_sub, angle: mid })
  } else {
    // Evenly distribute count items across the spread arc.
    for (let k = 0; k < count; k += 1) {
      const t = count === 1 ? 0.5 : k / (count - 1)
      const angle = mid - spread / 2 + t * spread
      out.push({ x: cx + Math.cos(angle) * R_sub, y: cy + Math.sin(angle) * R_sub, angle })
    }
  }
  return out
}

/** Build an SVG path string for a wedge boundary (annular sector). */
export function sectorPath(i, cx, cy, rInner, rOuter) {
  const { start, end } = sectorBounds(i)
  const x1 = cx + Math.cos(start) * rInner
  const y1 = cy + Math.sin(start) * rInner
  const x2 = cx + Math.cos(end) * rInner
  const y2 = cy + Math.sin(end) * rInner
  const x3 = cx + Math.cos(end) * rOuter
  const y3 = cy + Math.sin(end) * rOuter
  const x4 = cx + Math.cos(start) * rOuter
  const y4 = cy + Math.sin(start) * rOuter
  // Two short arcs, sweep flag = 1 for outward, 0 for inward.
  return [
    `M ${x1} ${y1}`,
    `A ${rInner} ${rInner} 0 0 1 ${x2} ${y2}`,
    `L ${x3} ${y3}`,
    `A ${rOuter} ${rOuter} 0 0 0 ${x4} ${y4}`,
    'Z',
  ].join(' ')
}
