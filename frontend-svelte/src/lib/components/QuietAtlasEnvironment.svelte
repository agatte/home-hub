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
    <p class="weather-kicker">02 / THE ENVIRONMENT</p>
    <h2 id="weather-band-title">Outside, as reported.</h2>
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
  <p class="weather-source">Source: HomeHub <code>GET /api/weather</code> (NWS-backed). Receipt is not station-observation freshness; cached conditions may be older. Not a live indoor comfort or lighting signal.</p>
</section>

<style>
  .weather-band {display:grid;grid-template-columns:minmax(160px,.9fr) minmax(180px,1fr) minmax(230px,1.25fr);gap:clamp(12px,2vw,24px);align-items:center;margin-top:23px;padding:19px 0 21px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);color:var(--ink);}
  .weather-lead {min-width:0;}
  .weather-kicker {color:var(--gold);font-size:10px;letter-spacing:.14em;font-weight:750;margin:0 0 9px;}
  h2 {font-size:clamp(20px,2vw,26px);letter-spacing:-.035em;font-weight:600;margin:0;}
  .weather-values {display:flex;align-items:center;gap:18px;min-width:0;}
  .temp {font:400 clamp(30px,3vw,43px)/1.08 Georgia,"Times New Roman",serif;white-space:nowrap;}
  .weather-conditions {display:flex;flex-direction:column;gap:5px;min-width:0;}
  .weather-conditions strong {font-size:13px;font-weight:600;overflow-wrap:anywhere;}
  .weather-conditions span {color:var(--muted);font-size:11px;line-height:1.4;overflow-wrap:anywhere;}
  .weather-unavailable {color:var(--muted);font-size:13px;line-height:1.5;margin:0;}
  .weather-source {color:var(--muted);font-size:10px;line-height:1.55;margin:0;max-width:430px;}
  code {font:inherit;color:var(--gold);overflow-wrap:anywhere;}
  @media(max-width:1000px){.weather-band{grid-template-columns:minmax(0,1fr) minmax(0,1.5fr)}.weather-source{grid-column:1/-1}}
  @media(max-width:700px){.weather-band{margin-top:15px;padding:14px 1px;gap:10px;grid-template-columns:minmax(0,.9fr) minmax(0,1.25fr)}.weather-kicker{font-size:8px;margin-bottom:5px}h2{font-size:17px}.temp{font-size:27px}.weather-values{gap:10px}.weather-conditions strong{font-size:11px}.weather-conditions span{font-size:10px}.weather-source{font-size:9px;line-height:1.4}}
  @media(max-width:360px){.weather-band{grid-template-columns:1fr}.weather-values{margin-top:2px}.weather-source{grid-column:1}}
</style>
