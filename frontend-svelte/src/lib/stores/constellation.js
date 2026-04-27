// Constellation model — derives a {nodes, links} graph from the live
// pipeline snapshot (inner ring of fusion voters) plus an optional
// outer ring of non-voting context signals.
//
// Node types:
//   nucleus — center, fusion-winning mode
//   lane    — a fusion voter (process/camera/audio_ml/rule_engine/
//             presence), linked to the nucleus with edge thickness
//             proportional to weight
//   factor  — a sub-signal the lane is considering, orbits its parent
//             lane, no edges
//   context — a non-voting input (time/weather/override/sonos), orbits
//             at a fixed outer radius, no edges, visually distinct

import { derived } from 'svelte/store'
import { pipeline } from './pipeline.js'
import { automation } from './automation.js'
import { sonos } from './sonos.js'
import { presence } from './presence.js'
import { weather } from './weather.js'

// Inner-ring lane order — matches backend SIGNAL_SOURCES. The behavioral
// lane was removed 2026-04-27 after the LightGBM predictor collapsed to a
// single output class; the predictor still runs in shadow but no longer
// contributes to fusion.
const LANE_ORDER = [
  'process', 'camera', 'audio_ml', 'rule_engine', 'presence',
]

const LANE_META = {
  process:     { label: 'Process', icon: 'cpu' },
  camera:      { label: 'Camera',  icon: 'video' },
  audio_ml:    { label: 'Audio',   icon: 'mic' },
  rule_engine: { label: 'Rules',   icon: 'clock' },
  presence:    { label: 'Presence', icon: 'wifi' },
}

// Ordered outer-ring slots for context bubbles. Kept stable so position
// doesn't shuffle between renders.
const CONTEXT_ORDER = ['time', 'weather', 'presence', 'override', 'sonos']

function titleCase(str) {
  if (!str) return ''
  return str.charAt(0).toUpperCase() + str.slice(1)
}

function formatAgo(iso) {
  if (!iso) return ''
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

/**
 * Build the 5 outer-ring context nodes from the aggregated stores.
 * `active` controls whether the bubble reads as live / noteworthy
 * (brighter fill) vs ambient-status (dim fill).
 */
function contextNodes({ pipelineCur, automation, sonos, presence, weather }) {
  const out = []
  const output = pipelineCur?.output || {}

  const timePeriod = output.time_period || ''
  out.push({
    id: 'context:time',
    type: 'context',
    key: 'time',
    label: 'Time',
    display: timePeriod ? titleCase(timePeriod.replace(/_/g, ' ')) : '—',
    active: !!timePeriod,
  })

  if (weather) {
    const t = weather.temp != null ? `${Math.round(weather.temp)}°` : ''
    const d = weather.description || ''
    out.push({
      id: 'context:weather',
      type: 'context',
      key: 'weather',
      label: 'Weather',
      display: [t, d].filter(Boolean).join(' ') || '—',
      active: true,
    })
  } else {
    out.push({
      id: 'context:weather',
      type: 'context',
      key: 'weather',
      label: 'Weather',
      display: '—',
      active: false,
    })
  }

  const presenceState = presence?.state || 'unknown'
  let presenceDisplay = titleCase(presenceState)
  if (presenceState === 'away' && presence?.away_duration_minutes != null) {
    presenceDisplay = `Away ${presence.away_duration_minutes}m`
  } else if (presenceState === 'home' && presence?.last_seen) {
    presenceDisplay = `Home · ${formatAgo(presence.last_seen)}`
  }
  out.push({
    id: 'context:presence',
    type: 'context',
    key: 'presence',
    label: 'Phone',
    display: presenceDisplay,
    active: presenceState !== 'unknown',
  })

  const overrideActive = !!automation?.manual_override
  const overrideMode = automation?.override_mode || automation?.mode || ''
  out.push({
    id: 'context:override',
    type: 'context',
    key: 'override',
    label: 'Override',
    display: overrideActive
      ? `${titleCase(overrideMode)} (manual)`
      : 'auto',
    active: overrideActive,
  })

  const playing = sonos?.state === 'PLAYING'
  const track = sonos?.track || ''
  out.push({
    id: 'context:sonos',
    type: 'context',
    key: 'sonos',
    label: 'Sonos',
    display: playing ? (track || 'Playing') : titleCase((sonos?.state || 'stopped').toLowerCase().replace(/_/g, ' ')),
    active: playing,
  })

  // Preserve declared order — this matters for the evenly-spaced outer
  // ring layout in ConstellationView.
  return CONTEXT_ORDER
    .map((k) => out.find((n) => n.key === k))
    .filter(Boolean)
}

/**
 * @param {any} current
 * @param {any} [ctxInputs]
 */
function snapshotToGraph(current, ctxInputs = null) {
  const fusion = current?.fusion || null
  const output = current?.output || null
  if (!fusion) {
    const baseNodes = ctxInputs ? contextNodes(ctxInputs) : []
    return { nodes: baseNodes, links: [], timestamp: null, fusedMode: null, fusedConfidence: 0 }
  }

  const fusedMode = fusion.fused_mode || output?.mode || 'idle'
  const fusedConfidence = fusion.fused_confidence ?? 0

  /** @type {any[]} */
  const nodes = [{
    id: 'nucleus',
    type: 'nucleus',
    mode: fusedMode,
    confidence: fusedConfidence,
    agreement: fusion.agreement ?? 0,
    autoApply: !!fusion.auto_apply,
    timePeriod: output?.time_period || '',
  }]

  /** @type {any[]} */
  const links = []

  for (const lane of LANE_ORDER) {
    const sig = fusion.signals?.[lane] || null
    const meta = LANE_META[lane]
    const hasData = !!(sig && sig.mode)

    const laneId = `lane:${lane}`
    nodes.push({
      id: laneId,
      type: 'lane',
      lane,
      label: meta.label,
      icon: meta.icon,
      mode: hasData ? sig.mode : null,
      confidence: sig?.confidence ?? 0,
      weight: sig?.weight ?? 0,
      agrees: !!sig?.agrees,
      stale: !!sig?.stale,
      lastUpdate: sig?.last_update || null,
      hasData,
      factors: Array.isArray(sig?.factors) ? sig.factors : [],
    })

    links.push({
      source: laneId,
      target: 'nucleus',
      weight: sig?.weight ?? 0,
      agrees: !!sig?.agrees,
      stale: !!sig?.stale,
      hasData,
    })

    if (hasData && Array.isArray(sig.factors)) {
      for (const f of sig.factors) {
        nodes.push({
          id: `factor:${lane}:${f.key}`,
          type: 'factor',
          parentId: laneId,
          lane,
          laneMode: sig.mode,
          agrees: !!sig.agrees,
          stale: !!(sig.stale || f.stale),
          key: f.key,
          label: f.label || f.key,
          display: f.display ?? String(f.value ?? ''),
          value: f.value,
          impact: typeof f.impact === 'number' ? f.impact : 0.5,
        })
      }
    }
  }

  if (ctxInputs) {
    nodes.push(...contextNodes(ctxInputs))
  }

  return {
    nodes,
    links,
    timestamp: fusion.timestamp || null,
    fusedMode,
    fusedConfidence,
  }
}

/**
 * Voters-only derived store — memoized by `fusion.timestamp`. Kept for
 * backward compatibility with callers that don't care about context.
 */
let _lastTs = /** @type {string | null} */ (null)
let _lastGraph = snapshotToGraph(null)

export const constellation = derived(pipeline, ($p) => {
  const current = $p.current
  const ts = current?.fusion?.timestamp || null
  if (ts && ts === _lastTs) return _lastGraph
  _lastTs = ts
  _lastGraph = snapshotToGraph(current)
  return _lastGraph
})

/**
 * Full graph including the outer-ring context bubbles. Rebuilds whenever
 * any of the upstream stores change — context updates frequently (sonos,
 * override, presence) so we don't memoize by timestamp here.
 */
export const constellationWithContext = derived(
  [pipeline, automation, sonos, presence, weather],
  ([$pipeline, $automation, $sonos, $presence, $weather]) => snapshotToGraph(
    $pipeline.current,
    {
      pipelineCur: $pipeline.current,
      automation: $automation,
      sonos: $sonos,
      presence: $presence,
      weather: $weather,
    },
  ),
)
