<script>
  // Display-only exterior weather. Response receipt is not source observation age.
  import { onMount } from 'svelte'
  import { weatherSky } from '$lib/quietAtlas/widgetTone.js'
  import { Sun, MoonStar, CloudSun, CloudMoon, Cloud, CloudRain, CloudLightning, Snowflake, CloudFog } from 'lucide-svelte'
  import { connected } from '$lib/stores/connection.js'
  import {
    newWeatherSnapshot, weatherConnectionChanged, invalidateWeatherRead,
    beginWeatherRead, acceptWeatherRead, failWeatherRead, weatherPresentation,
  } from '$lib/quietAtlas/weatherSnapshot.js'

  let snapshot = newWeatherSnapshot()
  let nowMs = 0
  $: view = weatherPresentation(snapshot, nowMs)
  $: sky = weatherSky(view)
  const skyIcons = { sun: Sun, night: MoonStar, 'partly-day': CloudSun, 'partly-night': CloudMoon, cloud: Cloud, 'cloud-night': Cloud, rain: CloudRain, 'rain-night': CloudRain, storm: CloudLightning, snow: Snowflake, mist: CloudFog, clear: Cloud, neutral: null }
  $: skyIcon = skyIcons[sky]

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

<section class="weather-band" aria-labelledby="weather-band-title" data-status={view.status} data-tone={sky}>
  {#if skyIcon}<div class="sky-art" aria-hidden="true"><svelte:component this={skyIcon} size={78} strokeWidth={1.25} /></div>{/if}
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
  .weather-band {
    --sky-start: #28332e; --sky-end: #151e1a; --sky-glow: rgba(158,174,157,.22); --sky-ink: #dce7df;
    position:relative;isolation:isolate;overflow:hidden;min-width:0;
    display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px 24px;align-items:center;
    margin-top:18px;padding:22px;border:1px solid rgba(222,233,245,.23);border-radius:var(--hh-radius-panel,20px);
    background:radial-gradient(ellipse at 92% 0%,var(--sky-glow),transparent 72%),linear-gradient(132deg,var(--sky-start),var(--sky-end));
    color:#faf8f5;
  }
  .weather-band[data-tone='sun'] {--sky-start:#215581;--sky-end:#325b79;--sky-glow:rgba(255,209,116,.80);--sky-ink:#ffe5a4;}
  .weather-band[data-tone='night'] {--sky-start:#111e43;--sky-end:#203c6a;--sky-glow:rgba(120,155,233,.46);--sky-ink:#d5e5ff;}
  .weather-band[data-tone='partly-day'] {--sky-start:#234c70;--sky-end:#49728e;--sky-glow:rgba(236,212,162,.67);--sky-ink:#ffedc6;}
  .weather-band[data-tone='partly-night'] {--sky-start:#172746;--sky-end:#33486a;--sky-glow:rgba(156,175,218,.46);--sky-ink:#dbe5f5;}
  .weather-band[data-tone='cloud'],.weather-band[data-tone='clear'] {--sky-start:#35495e;--sky-end:#64798a;--sky-glow:rgba(198,216,230,.48);--sky-ink:#edf3f7;}
  .weather-band[data-tone='cloud-night'] {--sky-start:#1e293e;--sky-end:#424e65;--sky-glow:rgba(148,165,194,.34);--sky-ink:#dce4f0;}
  .weather-band[data-tone='rain'] {--sky-start:#173c56;--sky-end:#32677f;--sky-glow:rgba(115,191,221,.38);--sky-ink:#c9ecfc;}
  .weather-band[data-tone='rain-night'] {--sky-start:#142b43;--sky-end:#244c65;--sky-glow:rgba(96,163,207,.41);--sky-ink:#c4e7fd;}
  .weather-band[data-tone='storm'] {--sky-start:#272143;--sky-end:#4b426d;--sky-glow:rgba(159,144,218,.46);--sky-ink:#efdcff;}
  .weather-band[data-tone='snow'] {--sky-start:#29465b;--sky-end:#597b91;--sky-glow:rgba(199,236,255,.52);--sky-ink:#effaff;}
  .weather-band[data-tone='mist'] {--sky-start:#35494e;--sky-end:#586d77;--sky-glow:rgba(203,221,222,.44);--sky-ink:#e1eeef;}
  .sky-art {grid-column:2;grid-row:1/3;align-self:center;justify-self:center;display:grid;place-items:center;color:var(--sky-ink);width:116px;height:104px;filter:drop-shadow(0 4px 20px var(--sky-glow));pointer-events:none;}
  .weather-lead,.weather-values,.weather-unavailable {grid-column:1;min-width:0;}
  .weather-lead {grid-row:1;}
  .weather-values,.weather-unavailable {grid-row:2;}
  .weather-kicker {color:var(--sky-ink);font-size:11px;letter-spacing:.12em;font-weight:750;margin:0 0 4px;}
  h2 {font-size:18px;letter-spacing:-.025em;font-weight:620;margin:0;}
  .weather-values {display:flex;align-items:center;flex-wrap:wrap;gap:8px 16px;}
  .temp {font-size:clamp(38px,6vw,54px);font-weight:600;letter-spacing:-.055em;line-height:1.08;white-space:nowrap;}
  .weather-conditions {display:flex;flex-direction:column;gap:4px;min-width:0;}
  .weather-conditions strong {font-size:15px;font-weight:650;overflow-wrap:anywhere;}
  .weather-conditions span {color:#edf1f4;font-size:13px;line-height:1.4;overflow-wrap:anywhere;}
  .weather-unavailable {color:#e0e8e3;font-size:14px;line-height:1.45;margin:0;}
  .weather-details {grid-column:1/-1;font-size:12px;color:#edf1f4;border-top:1px solid rgba(242,246,250,.19);margin-top:5px;}
  .weather-details summary {min-height:44px;display:flex;align-items:center;cursor:pointer;}
  .weather-details summary:focus-visible {outline:3px solid #f6e5c8;outline-offset:3px;}
  .weather-source {color:#edf1f4;font-size:12px;line-height:1.5;margin:8px 0 0;max-width:70ch;}
  code {font:inherit;color:inherit;overflow-wrap:anywhere;}
  @media(max-width:700px) {
    .weather-band {grid-template-columns:minmax(0,1fr) 84px;gap:7px 12px;margin-top:14px;padding:16px;}
    .weather-values {align-items:flex-start;flex-direction:column;gap:6px;}
    .sky-art {width:84px;height:92px;}
    .sky-art :global(svg) {width:68px;height:68px;}
    .weather-kicker {font-size:10px;}
    h2 {font-size:17px;}
    .temp {font-size:46px;}
  }
</style>