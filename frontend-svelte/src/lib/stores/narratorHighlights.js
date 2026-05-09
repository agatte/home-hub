// narratorHighlights store — fetches the analytics-narrator agent's
// structured highlights JSON sidecar so the SectorBoard can decorate the
// "today's story" wedge and any anomaly-flagged inputs.
//
// The sidecar shape (see ~/.claude/agents/analytics-narrator.md):
//   {
//     date: "YYYY-MM-DD",
//     headline_input: "process" | "camera" | ... | null,
//     headline_reason: "<short sentence>",
//     anomaly_inputs: [<sector-id>, ...],
//     mode_share_pct: {<mode>: <int>},
//     compared_to_baseline_7d: {<mode>: <int delta>}
//   }
//
// Empty default `{}` when no sidecar exists yet — frontend treats absence
// of `headline_input` as "no decoration."

import { writable } from 'svelte/store'

import { apiGet } from '$lib/api.js'

/** @typedef {{date: string|null, headline_input: string|null, headline_reason: string, anomaly_inputs: string[], mode_share_pct: Record<string, number>, compared_to_baseline_7d: Record<string, number>}} HighlightsPayload */

/** @type {import('svelte/store').Writable<HighlightsPayload>} */
export const narratorHighlights = writable({
  date: null,
  headline_input: null,
  headline_reason: '',
  anomaly_inputs: [],
  mode_share_pct: {},
  compared_to_baseline_7d: {},
})

let _initialized = false

/**
 * Fetch the latest highlights JSON. Idempotent — calling twice is a no-op.
 * SectorBoard calls this on mount; it doesn't need to refresh frequently
 * since the narrator agent runs on-demand (or eventually nightly via runbook).
 */
export async function loadNarratorHighlights() {
  if (_initialized) return
  _initialized = true
  try {
    const resp = /** @type {{date: string|null, highlights: Partial<HighlightsPayload>}} */ (
      await apiGet('/api/analytics/digest/highlights')
    )
    const h = resp?.highlights || {}
    narratorHighlights.set({
      date: resp?.date ?? null,
      headline_input: typeof h.headline_input === 'string' ? h.headline_input : null,
      headline_reason: typeof h.headline_reason === 'string' ? h.headline_reason : '',
      anomaly_inputs: Array.isArray(h.anomaly_inputs) ? h.anomaly_inputs : [],
      mode_share_pct: (h.mode_share_pct && typeof h.mode_share_pct === 'object') ? h.mode_share_pct : {},
      compared_to_baseline_7d: (h.compared_to_baseline_7d && typeof h.compared_to_baseline_7d === 'object') ? h.compared_to_baseline_7d : {},
    })
  } catch {
    // Empty default already in the store; nothing to do on fetch failure.
  }
}
