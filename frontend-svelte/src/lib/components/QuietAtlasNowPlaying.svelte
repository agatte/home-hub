<script>
  import { onMount } from 'svelte'
  import { Music, Play, Pause, SkipBack, SkipForward, Volume2 } from 'lucide-svelte'
  import { connected, deviceStatus } from '$lib/stores/connection.js'
  import { sonosLiveReport } from '$lib/stores/sonos.js'
  import { sonosCommand } from '$lib/stores/init.js'
  import { musicPlaybackReport, recentPlaybackReport } from '$lib/quietAtlas/musicPlaybackReport.js'

  /** @type {ReturnType<typeof musicPlaybackReport>} */
  let report = null
  /** @type {number | null} */
  let receivedAt = null
  let now = 0
  let message = ''
  let artFailed = false
  let artSource = ''
  /** @type {AbortController | null} */
  let pending = null
  let active = false
  let visible = false
  let nextReadAt = 0
  $: available = $connected && $deviceStatus.sonos && visible
  $: current = recentPlaybackReport(report, receivedAt, now, available)
  $: if ((current?.art_url ?? '') !== artSource) { artSource = current?.art_url ?? ''; artFailed = false }

  function invalidate() {
    pending?.abort(); pending = null
    report = null; receivedAt = null; message = ''; nextReadAt = 0
  }

  /** @param {unknown} data */
  function accept(data) {
    report = musicPlaybackReport(data)
    receivedAt = report ? Date.now() : null
    now = Date.now()
    if (report && message.startsWith('Request sent.')) message = 'Speaker report refreshed; command acceptance is not confirmed by this report.'
  }

  async function refresh() {
    if (!active || !visible || !$connected || !$deviceStatus.sonos || pending) return
    const request = new AbortController()
    pending = request
    nextReadAt = Date.now() + 15000
    const timeout = window.setTimeout(() => request.abort(), 8000)
    try {
      const response = await fetch('/api/sonos/status', {cache:'no-store', signal:request.signal})
      if (!response.ok) throw new Error('Unavailable')
      const data = await response.json()
      if (active && pending === request) accept(data)
    } catch {
      if (active && pending === request) { report = null; receivedAt = null }
    } finally {
      window.clearTimeout(timeout)
      if (pending === request) pending = null
    }
  }

  onMount(() => {
    active = true
    visible = document.visibilityState === 'visible'
    const sync = () => { invalidate(); void refresh() }
    const onVisibility = () => { visible = document.visibilityState === 'visible'; sync() }
    let wasConnected = $connected
    let wasSonos = $deviceStatus.sonos
    const unsubscribeConnection = connected.subscribe(value => { if (value !== wasConnected) { wasConnected = value; sync() } })
    const unsubscribeDevice = deviceStatus.subscribe(value => { if (value.sonos !== wasSonos) { wasSonos = value.sonos; sync() } })
    let initial = true
    const unsubscribeSonos = sonosLiveReport.subscribe(value => {
      if (initial) { initial = false; return }
      // The store's initial value may belong to a previous connection. A new
      // report wins over an outstanding read; no optimistic playback updates.
      if (!value || !active || !visible || !$connected || !$deviceStatus.sonos) return
      pending?.abort(); pending = null
      accept(value)
    })
    document.addEventListener('visibilitychange', onVisibility)
    void refresh()
    const timer = window.setInterval(() => {
      now = Date.now()
      if (now >= nextReadAt) void refresh()
    },1000)
    return () => { active = false; invalidate(); window.clearInterval(timer); unsubscribeConnection(); unsubscribeDevice(); unsubscribeSonos(); document.removeEventListener('visibilitychange',onVisibility) }
  })

  /** @param {string} action @param {Record<string, unknown>} [params] */
  function command(action, params = {}) {
    if (!recentPlaybackReport(report, receivedAt, Date.now(), $connected && $deviceStatus.sonos && visible)) return
    message = sonosCommand(action, params) ? 'Request sent. Waiting for the speaker report.' : 'Request not sent. Check the connection.'
  }
  /** @param {Event} event */
  function volumeChanged(event) {
    const input = /** @type {HTMLInputElement} */ (event.currentTarget)
    const value = Number(input.value)
    // Revert the input to the reported value; sending is not an ACK.
    if (current) input.value = String(current.volume)
    if (Number.isFinite(value)) command('volume', {volume:value})
  }
</script>

<section class="now-playing" aria-labelledby="now-playing-title">
  {#if current && artSource && !artFailed}
    <img class="art-wash" src={artSource} alt="" on:error={() => artFailed = true} />
  {/if}
  <div class="now-content">
    <div class="art-tile">
      {#if current && artSource && !artFailed}
        <img src={artSource} alt="" on:error={() => artFailed = true} />
      {:else}<Music size={42} strokeWidth={1.3} aria-hidden="true" />{/if}
    </div>
    <div class="now-copy">
      <p class="eyebrow" id="now-playing-title">NOW PLAYING &middot; SONOS</p>
      {#if current}
        <p class="state">{current.state === 'PLAYING' ? 'Playing' : current.state === 'PAUSED_PLAYBACK' ? 'Paused' : current.state === 'TRANSITIONING' ? 'Transitioning' : 'Stopped'}</p>
        <h2>{current.track || 'No track reported'}</h2>
        {#if current.artist}<p>{current.artist}</p>{/if}
        {#if current.album}<small>{current.album}</small>{/if}
      {:else}
        <h2>Playback unavailable</h2>
        <p>Waiting for a recent speaker report. Controls remain unavailable.</p>
      {/if}
    </div>
    <div class="transport" aria-label="Sonos playback controls">
      <button type="button" aria-label="Previous track" disabled={!current} on:click={() => command('previous')}><SkipBack size={21} aria-hidden="true" /></button>
      <button class="play" type="button" aria-label={current?.state === 'PLAYING' ? 'Pause' : 'Play'} disabled={!current || current.state === 'TRANSITIONING'} on:click={() => command(current?.state === 'PLAYING' ? 'pause' : 'play')}>
        {#if current?.state === 'PLAYING'}<Pause size={25} aria-hidden="true" />{:else}<Play size={25} aria-hidden="true" />{/if}
      </button>
      <button type="button" aria-label="Next track" disabled={!current} on:click={() => command('next')}><SkipForward size={21} aria-hidden="true" /></button>
      {#if current}<label class="volume"><Volume2 size={17} aria-hidden="true" /><span>Volume {current.volume}%</span><input aria-label="Sonos volume" type="range" min="0" max="100" value={current.volume} on:change={volumeChanged} /></label>{/if}
    </div>
    <p class="receipt" role="status">{message || (current ? 'Reported by HomeHub; playback changes require a speaker report.' : 'No recent report.')}</p>
  </div>
</section>

<style>
  .now-playing {position:relative;overflow:hidden;isolation:isolate;border:1px solid var(--hh-line);border-radius:24px;background:var(--hh-card-background);min-width:0;}
  .art-wash {position:absolute;width:100%;height:100%;inset:0;object-fit:cover;filter:blur(48px) brightness(.48);transform:scale(1.16);z-index:-1;}
  .now-content {display:grid;grid-template-columns:minmax(0,1fr);gap:20px;padding:clamp(18px,2.8vw,30px);background:linear-gradient(150deg,rgba(16,23,20,.28),rgba(16,23,20,.92) 72%);color:var(--hh-ink);}
  .now-copy {min-width:0;display:grid;gap:7px;overflow-wrap:anywhere;}
  .eyebrow {font-size:10px;font-weight:750;letter-spacing:.14em;color:var(--hh-accent);}
  .state {font-size:12px;color:var(--hh-accent);}
  .now-copy small,.receipt {font-size:12px;color:var(--hh-muted);}
  h2 {font:500 clamp(25px,3vw,39px)/1.12 var(--hh-display);letter-spacing:-.035em;margin:0;}
  .art-tile {aspect-ratio:1;display:grid;place-items:center;width:min(100%,276px);justify-self:center;background:linear-gradient(145deg,#43534b,#26322d);border:1px solid var(--hh-line);border-radius:16px;overflow:hidden;min-width:0;color:var(--hh-muted);box-shadow:0 18px 30px rgba(0,0,0,.24);}
  .art-tile img {width:100%;height:100%;object-fit:cover;}
  .transport {display:flex;flex-wrap:wrap;justify-content:center;align-items:center;gap:12px;}
  button {width:48px;height:48px;display:grid;place-items:center;border:0;border-radius:50%;background:transparent;color:var(--hh-ink);cursor:pointer;}
  button:not(:disabled):hover {background:var(--hh-control-hover);}
  button.play {width:64px;height:64px;background:var(--hh-accent);color:#20241f;}
  button.play:not(:disabled):hover {background:#f0dbb7;}
  button:disabled {opacity:.42;cursor:not-allowed;}
  button:focus-visible,input:focus-visible {outline:3px solid var(--hh-focus);outline-offset:3px;}
  .volume {display:flex;align-items:center;gap:8px;flex:1 1 100%;min-width:0;font-size:12px;color:var(--hh-muted);}
  .volume input {flex:1;min-width:55px;accent-color:var(--hh-accent);min-height:44px;}
  .receipt {min-height:18px;line-height:1.45;border-top:1px solid var(--hh-line);padding-top:12px;margin:0;}
  @media(max-width:1050px) {
    .now-content{grid-template-columns:minmax(88px,190px) minmax(0,1fr);align-items:center;}
    .transport,.receipt{grid-column:1/-1;}
    .art-tile{width:100%;}
  }
  @media(max-width:600px) {
    .now-content{grid-template-columns:84px minmax(0,1fr);gap:13px;padding:16px;}
    .art-tile{border-radius:11px;}
    h2{font-size:24px;}
    .transport{gap:8px;}
    button.play{width:56px;height:56px;}
  }
</style>
