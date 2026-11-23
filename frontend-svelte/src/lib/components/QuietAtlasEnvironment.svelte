<script>
  // Display-only exterior weather. Response receipt is not source observation age.
  import { onMount } from 'svelte'
  import { connected } from '$lib/stores/connection.js'
  import {
    newWeatherSnapshot, weatherConnectionChanged, invalidateWeatherRead,
    beginWeatherRead, acceptWeatherRead, failWeatherRead, weatherPresentation,
  } from '$lib/quietAtlas/weatherSnapshot.js'

  let snapshot = newWeatherSnapshot()
  let nowMs = 0
  $: view = weatherPresentation(snapshot, nowMs)

  onMount(() => {
    let mounted = true
    /** @type {AbortController | null} */
    let controller = null
    let retries = 0
    let nextPollAt = 0

    function abortRead() {
      controller?.abort()
      controller = null
    }

    async function refresh() {
      if (!mounted || !snapshot.connected || document.visibilityState !== 'visible') return
      const next = beginWeatherRead(snapshot)
      snapshot = next.state
      if (!next.ticket) return
      const ticket = next.ticket
      controller = new AbortController()
      const active = controller
      const timeout = window.setTimeout(() => active.abort(), 8000)
      nextPollAt = Date.now() + 300000
      try {
        const response = await fetch('/api/weather', { signal: active.signal, cache: 'no-store' })
        if (!response.ok) throw new Error('Weather unavailable')
        const body = await response.json()
        if (!mounted) return
        const receivedAt = Date.now()
        const accepted = acceptWeatherRead(snapshot, ticket, body, receivedAt)
        if (accepted !== snapshot) {
          snapshot = accepted
          nowMs = receivedAt
          retries = accepted.failed ? Math.min(3, retries + 1) : 0
          nextPollAt = receivedAt + (accepted.failed ? 30000 * 2 ** retries : 300000)
        }
      } catch {
        if (!mounted) return
        const failed = failWeatherRead(snapshot, ticket)
        if (failed !== snapshot) {
          snapshot = failed
          nowMs = Date.now()
          retries = Math.min(3, retries + 1)
          nextPollAt = nowMs + Math.min(240000, 30000 * 2 ** retries)
        }
      } finally {
        window.clearTimeout(timeout)
        if (controller === active) controller = null
      }
    }

    function connectionChanged(available) {
      if (!mounted) return
      abortRead()
      const previous = snapshot.connected
      snapshot = weatherConnectionChanged(snapshot, available)
      nowMs = Date.now()
      if (available && !previous && document.visibilityState === 'visible') {
        retries = 0
        nextPollAt = 0
        void refresh()
      }
    }

    function visibilityChanged() {
      if (!mounted) return
      abortRead()
      snapshot = invalidateWeatherRead(snapshot)
      nowMs = Date.now()
      if (document.visibilityState === 'visible' && snapshot.connected) {
        nextPollAt = 0
        void refresh()
      }
    }

    const unsubscribe = connected.subscribe(connectionChanged)
    document.addEventListener('visibilitychange', visibilityChanged)
    const ageTimer = window.setInterval(() => { nowMs = Date.now() }, 1000)
    const pollTimer = window.setInterval(() => {
      if (snapshot.connected && !snapshot.pending && document.visibilityState === 'visible' &&
          Date.now() >= nextPollAt) void refresh()
    }, 15000)

    return () => {
      mounted = false
      abortRead()
      snapshot = invalidateWeatherRead(snapshot)
      unsubscribe()
      document.removeEventListener('visibilitychange', visibilityChanged)
      window.clearInterval(ageTimer)
      window.clearInterval(pollTimer)
    }
  })
</script>

<section class="weather-band" aria-labelledby="weather-band-title" data-status={view.status}>
  <div class="weather-lead">
    <p class="weather-kicker">OUTSIDE</p>
    <h2 id="weather-band-title">Weather</h2>
  </div>
  {#if view.status === 'recent' && view.report}
    <div class="weather-values" role="status">
      <strong class="temp">{view.report.temp}°F</strong>
      <div class="weather-conditions">
        <strong>{view.report.description}</strong>
        <span>{view.report.city} · {view.report.feelsLike !== null ? 'Feels like ' + view.report.feelsLike + '°F' : 'Feels-like not reported'}</span>
      </div>
    </div>
  {:else}
    <p class="weather-unavailable" role="status">{view.message}</p>
  {/if}
  <details class="weather-details">
    <summary>Source &amp; freshness</summary>
    <p class="weather-source">Source: HomeHub <code>GET /api/weather</code> (NWS-backed). Receipt is not station-observation freshness; cached conditions may be older. Not a live indoor comfort or lighting signal.</p>
  </details>
</section>

<style>
  .weather-band {display:grid;grid-template-columns:minmax(110px,.65fr) minmax(150px,1.35fr) auto;gap:14px;align-items:center;margin-top:18px;padding:13px 2px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);color:var(--ink);min-width:0;}
  .weather-lead {min-width:0;}
  .weather-kicker {color:var(--gold);font-size:11px;letter-spacing:.1em;font-weight:750;margin:0 0 4px;}
  h2 {font-size:18px;letter-spacing:-.025em;font-weight:620;margin:0;}
  .weather-values {display:flex;align-items:center;gap:14px;min-width:0;}
  .temp {font-size:29px;font-weight:625;line-height:1.08;white-space:nowrap;}
  .weather-conditions {display:flex;flex-direction:column;gap:3px;min-width:0;}
  .weather-conditions strong {font-size:13px;font-weight:600;overflow-wrap:anywhere;}
  .weather-conditions span {color:var(--muted);font-size:12px;line-height:1.35;overflow-wrap:anywhere;}
  .weather-unavailable {color:var(--muted);font-size:13px;line-height:1.45;margin:0;}
  .weather-details {font-size:12px;color:var(--muted);}
  .weather-details summary {min-height:44px;display:flex;align-items:center;cursor:pointer;}
  .weather-details[open] {grid-column:1/-1;}
  .weather-details summary:focus-visible {outline:3px solid var(--gold);outline-offset:3px;}
  .weather-source {color:var(--muted);font-size:12px;line-height:1.5;margin:8px 0 0;max-width:70ch;}
  code {font:inherit;color:var(--gold);overflow-wrap:anywhere;}
  @media(max-width:700px) {
    .weather-band {grid-template-columns:minmax(70px,.6fr) minmax(0,1fr);gap:7px 12px;margin-top:10px;padding:12px 1px;}
    .weather-kicker {font-size:10px;}
    h2 {font-size:16px;}
    .weather-values {gap:9px;}
    .temp {font-size:26px;}
    .weather-details {grid-column:1/-1;}
    .weather-details summary {min-height:34px;font-size:12px;}
    .weather-source {font-size:11px;}
  }
  @media(max-width:360px) {
    .weather-band {grid-template-columns:minmax(65px,.55fr) minmax(0,1fr);}
  }
</style>