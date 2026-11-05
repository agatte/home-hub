<script>
  // #461: shared focused lighting detail. REST reads only; all writes stay in existing HomeHub.
  import { onMount } from 'svelte'
  import { page } from '$app/stores'
  import { connected } from '$lib/stores/connection.js'
  import QuietAtlasGroupSheet from '$lib/components/QuietAtlasGroupSheet.svelte'
  import { buildLightingOverview } from '$lib/quietAtlas/lightingModel.js'
  import { isKnownLightingGroup, lightingDetailOrigin } from '$lib/quietAtlas/navigation.js'
  import {
    newReadOnlySnapshot, connectionChanged, invalidateLightRead, beginLightRead,
    acceptLightRead, failLightRead, readStatus,
  } from '$lib/quietAtlas/lightSnapshot.js'

  let snapshot = newReadOnlySnapshot()
  let nowMs = Date.now()
  let mounted = false
  /** @type {AbortController | null} */
  let currentRequest = null
  let nextPollAt = 0
  $: snapshotStatus = readStatus(snapshot, nowMs)
  $: roomId = $page.params.groupId
  $: knownRoom = isKnownLightingGroup(roomId)
  $: room = buildLightingOverview(snapshot.fixtures, snapshotStatus === 'recent-read')
    .find((item) => item.id === roomId)
  $: origin = lightingDetailOrigin($page.url.searchParams)
  $: originLabel = origin === 'home' ? 'Home' : 'Control'
  $: returnHref = origin === 'home' ? '/quiet-atlas/home' : '/quiet-atlas/control'
  $: roomStatus = snapshotStatus === 'recent-read' && room
    ? { on: 'Reported on', off: 'Reported off', mixed: 'Reported mixed', offline: 'Reported offline', partial: 'Partly available', unknown: 'Not verified' }[room.status] || 'Not verified'
    : 'Not verified'
  $: snapshotNote = snapshotStatus === 'disconnected'
    ? 'HomeHub is disconnected. Last values are not confirmed current.'
    : snapshotStatus === 'unverified'
      ? 'Waiting for a successful HomeHub lighting report.'
      : snapshotStatus === 'stale-read'
        ? 'The last lighting report is stale; actual lights may have changed.'
        : 'Recent HomeHub API response. Individual fixture and bridge freshness are still unverified.'

  function abortRead() {
    currentRequest?.abort()
    currentRequest = null
  }

  async function refresh() {
    if (!mounted || !snapshot.connected || document.visibilityState !== 'visible') return
    // Preserve still-fresh receipt evidence during routine GETs so unchanged
    // reports do not discard an unfinished local draft. The new requestId
    // supersedes older responses; connection/visibility still invalidate it.
    abortRead()
    const next = beginLightRead(snapshot)
    snapshot = next.state
    if (!next.ticket) return
    const ticket = next.ticket
    const controller = new AbortController()
    currentRequest = controller
    const timeout = window.setTimeout(() => controller.abort(), 8000)
    // Poll before the 30s receipt TTL: a delayed replacement GET must not
    // cause an unchanged, otherwise valid draft to disappear at expiry.
    // The 15s scheduler preserves an 8s fetch-timeout margin.
    nextPollAt = Date.now() + 15000
    try {
      const response = await fetch('/api/lights', { signal: controller.signal, cache: 'no-store' })
      if (!response.ok) throw new Error('Lighting report unavailable')
      const rows = await response.json()
      if (!mounted) return
      snapshot = acceptLightRead(snapshot, ticket, rows, Date.now())
      nowMs = Date.now()
    } catch {
      if (!mounted) return
      snapshot = failLightRead(snapshot, ticket)
      nowMs = Date.now()
      nextPollAt = nowMs + 15000
    } finally {
      window.clearTimeout(timeout)
      if (currentRequest === controller) currentRequest = null
    }
  }

  function onConnectionChanged(available) {
    if (!mounted) return
    abortRead()
    snapshot = connectionChanged(snapshot, available)
    snapshot = invalidateLightRead(snapshot)
    nowMs = Date.now()
    nextPollAt = 0
    if (available && document.visibilityState === 'visible') void refresh()
  }

  function onVisibilityChanged() {
    if (!mounted) return
    abortRead()
    snapshot = invalidateLightRead(snapshot)
    nowMs = Date.now()
    nextPollAt = 0
    if (document.visibilityState === 'visible' && snapshot.connected) void refresh()
  }

  onMount(() => {
    mounted = true
    const unsubscribe = connected.subscribe(onConnectionChanged)
    document.addEventListener('visibilitychange', onVisibilityChanged)
    const ageTimer = window.setInterval(() => { nowMs = Date.now() }, 1000)
    const pollTimer = window.setInterval(() => {
      if (snapshot.connected && !snapshot.pending && document.visibilityState === 'visible' &&
          Date.now() >= nextPollAt) void refresh()
    }, 15000)
    return () => {
      mounted = false
      abortRead()
      snapshot = invalidateLightRead(snapshot)
      unsubscribe()
      document.removeEventListener('visibilitychange', onVisibilityChanged)
      window.clearInterval(ageTimer)
      window.clearInterval(pollTimer)
    }
  })
</script>

<svelte:head>
  <title>Lighting detail · Quiet Atlas | HomeHub</title>
  <meta name="description" content="Read-only, non-modal lighting detail with source-qualified fixture reports." />
</svelte:head>

<main class="lighting-detail" aria-label="Focused lighting detail">
  <nav class="detail-nav" aria-label="Lighting detail navigation">
    <a class="return-link" href={returnHref} aria-label={'Back to ' + originLabel}>
      <span class="back-icon" aria-hidden="true">‹</span>
      <span>{originLabel}</span>
    </a>
    <span class="read-only-label">Quiet Atlas · Read-only preview</span>
  </nav>

  {#if !knownRoom || !room}
    <section class="unknown-room">
      <p class="eyebrow">LIGHTING / NOT FOUND</p>
      <h1>Room unavailable</h1>
      <p>This lighting group is not part of the verified HomeHub design inventory.</p>
      <a href={returnHref}>Return to {originLabel}</a>
    </section>
  {:else}
    <div class="detail-grid">
      <section class="room-overview" aria-labelledby="detail-room-title">
        <p class="eyebrow">YOUR APARTMENT / {origin === 'home' ? 'ATMOSPHERE' : 'LIGHT STUDIO'}</p>
        <h1 id="detail-room-title">{room.label}</h1>
        <p class="room-intro">A closer look at the room, without leaving the apartment behind.</p>
        <div class="room-visual" aria-hidden="true">
          <div class="halo"></div>
          <div class="fixture-dots">
            {#each room.fixtures as fixture (fixture.id)}
              <span class:reported-lit={snapshotStatus === 'recent-read' && fixture.on === true}></span>
            {/each}
          </div>
        </div>
        <div class="status-row">
          <span class="state-chip">{roomStatus}</span>
          {#if snapshotStatus === 'recent-read' && room.status !== 'partial' && room.status !== 'unknown' && room.status !== 'offline'}
            <span class="count-label">{room.onCount} of {room.total} reported on</span>
          {/if}
        </div>
        <p class="freshness" role="status">{snapshotNote}</p>
        <button type="button" class="refresh-button" on:click={refresh}>Refresh report</button>

        <div class="navigation-options">
          <a class="legacy-action" href="/#apartment-controls">
            <span><strong>Adjust lights now</strong><small>Open existing functional HomeHub controls</small></span>
            <span aria-hidden="true">↗</span>
          </a>
          {#if origin === 'home'}
            <a class="secondary-action" href="/quiet-atlas/control">
              Explore precision controls and scenes <span aria-hidden="true">→</span>
            </a>
          {:else}
            <a class="secondary-action" href="/quiet-atlas/home">
              Return to apartment atmosphere <span aria-hidden="true">→</span>
            </a>
          {/if}
        </div>
      </section>

      <div class="detail-inspector">
        <div class="detail-note">
          <p class="eyebrow">CONTROL / INDIVIDUAL LIGHTS</p>
          <p>Preview brightness changes for each fixture separately. No changes are sent.</p>
        </div>
        {#key room.id}
          <QuietAtlasGroupSheet inline={true} group={room} {snapshotStatus} fixtureStates={snapshot.fixtures} />
        {/key}
      </div>
    </div>
  {/if}
</main>

<style>
  .lighting-detail { min-height:100%; min-width:0; background:radial-gradient(ellipse at 8% 3%,rgba(145,170,120,.1),transparent 48%),#101a15; color:#edf0e8; padding:clamp(16px,2.7vw,38px) clamp(14px,3vw,44px) 54px; font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
  .lighting-detail * { box-sizing:border-box; }
  .lighting-detail a { text-decoration:none; }
  .lighting-detail a:focus-visible, .lighting-detail button:focus-visible { outline:3px solid #d2e4b9; outline-offset:3px; }
  .detail-nav { display:flex; align-items:center; justify-content:space-between; gap:12px; margin:0 auto 24px; max-width:1480px; }
  .return-link { display:inline-flex; align-items:center; gap:10px; min-height:48px; padding:7px 14px 7px 11px; background:rgba(182,205,166,.07); border:1px solid rgba(166,193,162,.28); border-radius:13px; color:#f0f1e9; font-weight:650; font-size:15px; }
  .back-icon { font:normal 29px/1 Georgia,serif; margin-top:-2px; }
  .read-only-label { font-size:12px; letter-spacing:.01em; color:#a9b9a9; text-align:right; }
  .detail-grid { max-width:1480px; margin:0 auto; display:grid; grid-template-columns:minmax(270px,.72fr) minmax(0,1.28fr); align-items:start; gap:clamp(18px,3.8vw,56px); }
  .room-overview { min-width:0; position:sticky; top:22px; padding:18px 0 0; }
  .eyebrow { font-size:11px; font-weight:750; letter-spacing:.14em; color:#a5bca9; margin:0; }
  h1 { font:400 clamp(38px,4.5vw,64px)/1.09 Georgia,"Times New Roman",serif; letter-spacing:-.04em; margin:13px 0 12px; overflow-wrap:anywhere; }
  .room-intro { color:#b9c9b9; font-size:15px; line-height:1.65; max-width:34ch; margin:0; }
  .room-visual { position:relative; margin:24px 0 18px; height:clamp(166px,19vw,272px); overflow:hidden; border:1px solid rgba(196,215,176,.16); border-radius:24px; background:radial-gradient(ellipse at 52% 105%,#6b654b88,transparent 56%),linear-gradient(135deg,#2c382c,#14231d 73%); display:flex; align-items:flex-end; justify-content:center; }
  .halo { position:absolute; width:62%; aspect-ratio:1; top:8%; border-radius:50%; background:radial-gradient(circle,#edca8749 0%,#a6986a24 37%,transparent 70%); filter:blur(10px); }
  .fixture-dots { position:relative; display:flex; gap:18px; padding-bottom:35px; }
  .fixture-dots span { width:14px; height:14px; border-radius:50%; background:#738478; border:2px solid #a3b49c; }
  .fixture-dots span.reported-lit { background:#e9ca94; box-shadow:0 0 18px #efca7a88; border-color:#f1dbab; }
  .status-row { display:flex; gap:9px; align-items:center; flex-wrap:wrap; }
  .state-chip { padding:7px 11px; background:#233629; border:1px solid #617d64; border-radius:999px; font-size:12px; color:#d3e3cb; }
  .count-label { font-size:13px; color:#b7c9bc; }
  .freshness { font-size:13px; line-height:1.6; color:#b8c5b5; margin:14px 0 0; max-width:44ch; }
  .refresh-button { margin-top:10px; min-height:44px; padding:9px 14px; border-radius:12px; background:transparent; border:1px solid #65876e; color:#d9ecce; font:600 13px system-ui,sans-serif; cursor:pointer; }
  .navigation-options { display:grid; gap:13px; margin-top:25px; }
  .legacy-action { display:flex; align-items:center; justify-content:space-between; gap:14px; min-height:64px; background:#e5ebdd; color:#1b3323; padding:13px 16px; border-radius:16px; }
  .legacy-action span:first-child { display:flex; flex-direction:column; gap:3px; }
  .legacy-action strong { font-size:15px; line-height:1.45; }
  .legacy-action small { color:#45644d; font-size:12px; line-height:1.45; }
  .secondary-action { display:inline-flex; align-items:center; justify-content:space-between; gap:12px; padding:8px 3px; min-height:44px; font-size:13px; font-weight:600; color:#c7dfbe; line-height:1.5; }
  .detail-inspector { min-width:0; }
  .detail-note { padding:12px 3px 18px; }
  .detail-note p:last-child { color:#b7c7b9; font-size:14px; line-height:1.5; margin:7px 0 0; }
  .unknown-room { max-width:630px; margin:30px auto; border:1px solid #56705c; border-radius:20px; padding:25px; }
  .unknown-room p { color:#b9c9b9; font-size:14px; line-height:1.6; }
  .unknown-room a { display:inline-flex; min-height:44px; align-items:center; color:#d6eccb; }
  @media(max-width:850px) {
    .detail-grid { grid-template-columns:minmax(0,1fr); gap:18px; }
    .room-overview { position:static; padding-top:3px; }
    .room-visual { height:180px; margin:19px 0 16px; }
    .detail-nav { margin-bottom:18px; }
  }
  @media(max-width:600px) {
    .lighting-detail { padding:13px 14px calc(38px + env(safe-area-inset-bottom,0px)); }
    .detail-nav { gap:6px; }
    .read-only-label { max-width:45%; font-size:11px; }
    .return-link { padding:7px 12px; min-height:48px; }
    h1 { font-size:clamp(36px,10vw,48px); margin:11px 0 9px; }
    .room-visual { height:150px; margin:15px 0 12px; }
    .room-intro { font-size:14px; line-height:1.55; }
    .navigation-options { margin-top:17px; }
    .detail-note { padding-top:4px; }
  }
  @media(prefers-reduced-motion:reduce) {
    .lighting-detail *, .lighting-detail *::before, .lighting-detail *::after { transition:none !important; animation:none !important; }
  }
</style>
