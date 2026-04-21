// Constellation model — derives a {nodes, links} graph from the live pipeline
// snapshot for the analytics force-directed view.
//
// Shape produced:
//   nodes: [
//     { id: 'nucleus', type: 'nucleus', mode, confidence, ... },
//     { id: 'lane:process', type: 'lane', lane, mode, weight, agrees, stale, lastUpdate, factors, ... },
//     { id: 'factor:process:foreground', type: 'factor', parentId, lane, key, label, display, impact, stale },
//     ...
//   ]
//   links: [
//     { source: 'lane:process', target: 'nucleus', weight, agrees, stale },
//     ...
//   ]
//
// Edges exist only between lane nodes and the nucleus. Factor pips orbit
// their parent lane via a custom radial force (see ConstellationView), not
// via explicit links — fewer strokes on screen keeps the view readable.

import { derived } from 'svelte/store'
import { pipeline } from './pipeline.js'

const LANE_ORDER = ['process', 'camera', 'audio_ml', 'behavioral', 'rule_engine']

const LANE_META = {
  process:     { label: 'Process', icon: 'cpu' },
  camera:      { label: 'Camera',  icon: 'video' },
  audio_ml:    { label: 'Audio',   icon: 'mic' },
  behavioral:  { label: 'Predict', icon: 'brain' },
  rule_engine: { label: 'Rules',   icon: 'clock' },
}

/** @param {any} current */
function snapshotToGraph(current) {
  const fusion = current?.fusion || null
  const output = current?.output || null
  if (!fusion) {
    return { nodes: [], links: [], timestamp: null, fusedMode: null, fusedConfidence: 0 }
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

    // Factor pips — orbit their parent lane, no edge to nucleus
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

  return {
    nodes,
    links,
    timestamp: fusion.timestamp || null,
    fusedMode,
    fusedConfidence,
  }
}

/**
 * Derived store: {nodes, links, timestamp, fusedMode, fusedConfidence}.
 * Memoized by `fusion.timestamp` — if the backend snapshot hasn't moved,
 * we return the previous reference so the simulation doesn't thrash.
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
