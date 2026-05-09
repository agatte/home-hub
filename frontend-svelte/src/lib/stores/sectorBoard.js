// Sector Board derived store — re-shapes live data into the 8-wedge model.
//
// Each sector exposes a uniform shape so the InputWedge component doesn't
// have to special-case voters vs context. Sub-bubbles for the four voter
// lanes come from the WS pipeline payload's `factors` arrays; sub-bubbles
// for time/weather/sonos are derived locally from existing Svelte stores.
// Light sub-bubbles come from the lights store.

import { derived } from 'svelte/store'

import { pipeline } from './pipeline.js'
import { automation } from './automation.js'
import { sonos as sonosStore } from './sonos.js'
import { weather as weatherStore } from './weather.js'
import { lights as lightsStore } from './lights.js'

const VOTER_KEYS = ['process', 'camera', 'audio', 'rules']
// pipeline payload uses backend-canonical keys for voters; we map for our id space.
const VOTER_BACKEND_KEY = {
  process: 'process',
  camera: 'camera',
  audio: 'audio_ml',
  rules: 'rule_engine',
}

const _DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

function titleCase(s) {
  if (!s) return ''
  return s.charAt(0).toUpperCase() + s.slice(1)
}

function voterSector(id, fusion) {
  const sig = fusion?.signals?.[VOTER_BACKEND_KEY[id]] || null
  const hasData = !!(sig && sig.mode)
  const factors = Array.isArray(sig?.factors) ? sig.factors.slice(0, 4) : []
  // Voter impact = its fusion weight, with a floor so the bubble is still
  // visible/readable when the lane is silent. Stale signals decay further.
  const weight = sig?.weight ?? 0
  let impactScore = 0.2 // baseline so never-zero
  if (hasData) impactScore = Math.max(0.25, weight)
  if (sig?.stale) impactScore = Math.min(impactScore, 0.25)
  return {
    id,
    kind: 'voter',
    hasData,
    mode: hasData ? sig.mode : null,
    weight,
    confidence: sig?.confidence ?? 0,
    agrees: !!sig?.agrees,
    stale: !!sig?.stale,
    lastUpdate: sig?.last_update || null,
    impactScore,
    factors: factors.map((f) => ({
      key: f.key,
      label: f.label || f.key,
      display: f.display ?? String(f.value ?? ''),
      impact: typeof f.impact === 'number' ? f.impact : 0.5,
      stale: !!f.stale,
    })),
  }
}

function timeSector(fusion) {
  const period = fusion?.signals?.process?.factors?.find((f) => f.key === 'time_period')?.display
    || fusion?.output?.time_period
    || ''
  const now = new Date()
  const factors = []
  if (period) {
    factors.push({
      key: 'time_period',
      label: 'Period',
      display: titleCase(String(period).replace(/_/g, ' ')),
      impact: 0.7,
      stale: false,
    })
  }
  factors.push({
    key: 'day_of_week',
    label: 'Day',
    display: _DOW[now.getDay()],
    impact: 0.3,
    stale: false,
  })
  factors.push({
    key: 'clock',
    label: 'Clock',
    display: now.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }),
    impact: 0.4,
    stale: false,
  })
  // Time impact peaks during evening/night/late_night transition windows
  // (when lighting decisions get most active) and dips mid-day.
  const periodLower = (period || '').toLowerCase().replace(/_/g, ' ')
  let impactScore = 0.4
  if (/late.?night/.test(periodLower)) impactScore = 0.85
  else if (periodLower === 'night') impactScore = 0.7
  else if (periodLower === 'evening') impactScore = 0.6
  else if (periodLower === 'morning') impactScore = 0.55
  return {
    id: 'time',
    kind: 'context',
    hasData: !!period,
    mode: null,
    weight: 0,
    confidence: 0,
    agrees: false,
    stale: false,
    impactScore,
    factors,
  }
}

function weatherSector(weather) {
  const factors = []
  if (weather?.description) {
    factors.push({
      key: 'condition',
      label: 'Condition',
      display: weather.description,
      impact: 0.7,
      stale: false,
    })
  }
  if (weather?.temp != null) {
    factors.push({
      key: 'temp',
      label: 'Temp',
      display: `${Math.round(weather.temp)}°F`,
      impact: 0.4,
      stale: false,
    })
  }
  // Weather impact peaks when condition triggers an effect overlay
  // (rain → candle, thunderstorm → sparkle, snow → opal) — those modes
  // observably change the lighting. Clear weather is mostly silent.
  const desc = (weather?.description || '').toLowerCase()
  let impactScore = 0.25
  if (/thunder|storm/.test(desc)) impactScore = 0.95
  else if (/rain|shower/.test(desc)) impactScore = 0.8
  else if (/snow|sleet|hail/.test(desc)) impactScore = 0.7
  else if (/fog|mist|haze/.test(desc)) impactScore = 0.55
  else if (/cloud|overcast/.test(desc)) impactScore = 0.45
  return {
    id: 'weather',
    kind: 'context',
    hasData: !!(weather && (weather.description || weather.temp != null)),
    mode: null,
    weight: 0,
    confidence: 0,
    agrees: false,
    stale: false,
    impactScore,
    factors,
  }
}

function sonosSector(sonos) {
  const factors = []
  const state = sonos?.state || 'STOPPED'
  const playing = state === 'PLAYING'
  factors.push({
    key: 'state',
    label: 'State',
    display: playing ? 'Playing' : titleCase(state.toLowerCase().replace(/_/g, ' ')),
    impact: playing ? 0.8 : 0.3,
    stale: false,
  })
  if (playing && sonos?.track) {
    factors.push({
      key: 'track',
      label: 'Track',
      display: sonos.track.length > 18 ? sonos.track.slice(0, 17) + '…' : sonos.track,
      impact: 0.6,
      stale: false,
    })
  }
  if (playing && sonos?.artist) {
    factors.push({
      key: 'artist',
      label: 'Artist',
      display: sonos.artist.length > 14 ? sonos.artist.slice(0, 13) + '…' : sonos.artist,
      impact: 0.4,
      stale: false,
    })
  }
  // Sonos impact peaks when actively playing — playing suppresses TTS,
  // drives autoplay-on-mode-change, holds the mode-change callback. When
  // stopped, Sonos is observationally silent in the apartment.
  const impactScore = playing ? 0.9 : 0.3
  return {
    id: 'sonos',
    kind: 'context',
    hasData: true,
    mode: null,
    weight: 0,
    confidence: 0,
    agrees: false,
    stale: false,
    impactScore,
    factors,
  }
}

function lightsSector(lights) {
  const list = Object.values(lights || {})
    .sort((a, b) => {
      const ai = parseInt(a.light_id, 10), bi = parseInt(b.light_id, 10)
      if (!isNaN(ai) && !isNaN(bi)) return ai - bi
      return (a.name || '').localeCompare(b.name || '')
    })
  // Lights impact = fraction lit, weighted by mean brightness. A dim
  // candle scene reads as "low impact" vs a bright working scene at peak.
  const onLights = list.filter((l) => l.on)
  let impactScore = 0.3
  if (list.length) {
    const onFraction = onLights.length / list.length
    const avgBri = onLights.length
      ? onLights.reduce((acc, l) => acc + (l.bri ?? 0), 0) / onLights.length / 254
      : 0
    impactScore = Math.max(0.3, 0.45 * onFraction + 0.55 * avgBri)
  }
  return {
    id: 'lights',
    kind: 'output',
    hasData: list.length > 0,
    mode: null,
    weight: 0,
    confidence: 0,
    agrees: false,
    stale: false,
    impactScore,
    factors: [], // lights are rendered specially via LightWedge
    lights: list,
  }
}

/**
 * Master derived store — re-shapes pipeline + ambient stores into the
 * eight-sector model the SectorBoard expects.
 */
export const sectorBoard = derived(
  [pipeline, automation, sonosStore, weatherStore, lightsStore],
  ([$pipeline, $automation, $sonos, $weather, $lights]) => {
    const fusion = $pipeline?.current?.fusion || null
    const output = $pipeline?.current?.output || null

    const fusedMode = fusion?.fused_mode || output?.mode || $automation?.mode || 'idle'
    const fusedConfidence = fusion?.fused_confidence ?? 0
    const overrideActive = !!$automation?.manual_override
    const dndActive = !!$automation?.dnd?.enabled

    return {
      mode: {
        current: fusedMode,
        confidence: fusedConfidence,
        source: $automation?.source || 'auto',
        override: overrideActive,
        dnd: dndActive,
      },
      sectors: {
        process: voterSector('process', fusion),
        camera: voterSector('camera', fusion),
        audio: voterSector('audio', fusion),
        rules: voterSector('rules', fusion),
        time: timeSector(fusion),
        weather: weatherSector($weather),
        sonos: sonosSector($sonos),
        lights: lightsSector($lights),
      },
    }
  },
)
