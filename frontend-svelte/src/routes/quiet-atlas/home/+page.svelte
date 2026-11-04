<script>
  // #270: opt-in read-only review; HomeHub status comes only from guarded REST.
  import { onMount } from 'svelte'
  import { connected } from '$lib/stores/connection.js'
  import QuietAtlasEnvironment from '$lib/components/QuietAtlasEnvironment.svelte'
  import { controlGroupHref, CONTROL_SCENES_HREF } from '$lib/quietAtlas/navigation.js'
  import {
    newHomeContextSnapshot, homeContextConnectionChanged, invalidateHomeContextRead,
    beginHomeContextRead, acceptHomeContextRead, failHomeContextRead, homeContextPresentation,
  } from '$lib/quietAtlas/homeContextSnapshot.js'
  import {
    newRecentActivityLog, recentActivityConnectionChanged, invalidateRecentActivity,
    beginRecentActivityRead, acceptRecentActivityRead, failRecentActivityRead,
    recentActivityPresentation, recentActivityTime,
  } from '$lib/quietAtlas/recentActivityLog.js'
  let activityLog = newRecentActivityLog()
  let activityNowMs = 0
  $: recentActivity = recentActivityPresentation(activityLog, activityNowMs)
  let daylight = false
  // Product-facing Home defaults to source-qualified context, not sample cards.
  // Illustrative cases remain an explicit, reversible design-review mode.
  let reviewExamples = false
  let sampleState = 'unavailable'
  let contextSnapshot = newHomeContextSnapshot()
  let contextNowMs = 0
  $: contextDisplay = homeContextPresentation(contextSnapshot, contextNowMs)

  const groups = [
    { id: 'living', name: 'Living', detail: 'L1', label: 'Browse Living lights' },
    { id: 'bedroom', name: 'Bedroom', detail: 'L2 · L5', label: 'Browse Bedroom lights' },
    { id: 'kitchen', name: 'Kitchen', detail: 'L3 · L4', label: 'Browse Kitchen lights' },
    { id: 'plant', name: 'Plant', detail: 'L6', label: 'Browse Plant lighting' },
  ]

  const examples = {
    unavailable: {
      title: 'No live context connected',
      description: 'House State and Activity have not been read by this design study.',
      kind: 'Unavailable',
    },
    stale: {
      title: 'Lighting reading unverified',
      description: 'A stale light reading cannot establish current bulb state or change House State.',
      kind: 'Stale example',
    },
    empty: {
      title: 'Nothing to report yet',
      description: 'A quiet, empty event rail should leave space for the apartment.',
      kind: 'Empty example',
    },
    attention: {
      title: 'Manual lighting ownership',
      description: 'An example reminder that manual controls take precedence over automatic suggestions.',
      kind: 'Attention example',
    },
  }

  $: example = examples[sampleState] ?? examples.unavailable

  onMount(() => {
    let mounted = true
    /** @type {AbortController | null} */
    let controller = null
    let failures = 0
    let nextPollAt = 0
    /** @type {AbortController | null} */
    let activityController = null
    let activityFailures = 0
    let nextActivityPollAt = 0

    function abortRead() {
      controller?.abort()
      controller = null
    }

    function abortActivityRead() {
      activityController?.abort()
      activityController = null
    }

    async function refreshRecentActivity() {
      if (!mounted || !activityLog.connected || document.visibilityState !== 'visible') return
      const next = beginRecentActivityRead(activityLog)
      activityLog = next.state
      if (!next.ticket) return
      const ticket = next.ticket
      activityController = new AbortController()
      const requestController = activityController
      const timeout = window.setTimeout(() => requestController.abort(), 8000)
      nextActivityPollAt = Date.now() + 60000
      try {
        const response = await fetch('/api/events/activity?days=1&limit=6&offset=0', {
          signal: requestController.signal, cache: 'no-store',
        })
        if (!response.ok) throw new Error('Activity history unavailable')
        const body = await response.json()
        if (!mounted) return
        const accepted = acceptRecentActivityRead(activityLog, ticket, body, Date.now())
        if (accepted !== activityLog) {
          activityLog = accepted
          activityNowMs = Date.now()
          activityFailures = accepted.failed ? Math.min(3, activityFailures + 1) : 0
          nextActivityPollAt = activityNowMs + (accepted.failed ? 30000 * activityFailures : 60000)
        }
      } catch {
        if (!mounted) return
        const failed = failRecentActivityRead(activityLog, ticket)
        if (failed !== activityLog) {
          activityLog = failed
          activityNowMs = Date.now()
          activityFailures = Math.min(3, activityFailures + 1)
          nextActivityPollAt = activityNowMs + Math.min(120000, 30000 * activityFailures)
        }
      } finally {
        window.clearTimeout(timeout)
        if (activityController === requestController) activityController = null
      }
    }

    async function refreshContext() {
      if (!mounted || !contextSnapshot.connected || document.visibilityState !== 'visible') return
      const next = beginHomeContextRead(contextSnapshot)
      contextSnapshot = next.state
      if (!next.ticket) return
      const ticket = next.ticket
      controller = new AbortController()
      const currentController = controller
      const timeout = window.setTimeout(() => currentController.abort(), 8000)
      nextPollAt = Date.now() + 30000
      try {
        const response = await fetch('/api/automation/status', { signal: currentController.signal, cache: 'no-store' })
        if (!response.ok) throw new Error('HomeHub status unavailable')
        const body = await response.json()
        if (!mounted) return
        const confirmedAt = Date.now()
        const accepted = acceptHomeContextRead(contextSnapshot, ticket, body, confirmedAt)
        if (accepted !== contextSnapshot) {
          contextSnapshot = accepted
          contextNowMs = confirmedAt
          if (!accepted.failed) {
            failures = 0
            nextPollAt = confirmedAt + 30000
          } else {
            failures = Math.min(3, failures + 1)
            nextPollAt = confirmedAt + Math.min(120000, 15000 * 2 ** failures)
          }
        }
      } catch {
        if (!mounted) return
        const failed = failHomeContextRead(contextSnapshot, ticket)
        if (failed !== contextSnapshot) {
          contextSnapshot = failed
          contextNowMs = Date.now()
          failures = Math.min(3, failures + 1)
          nextPollAt = contextNowMs + Math.min(120000, 15000 * 2 ** failures)
        }
      } finally {
        window.clearTimeout(timeout)
        if (controller === currentController) controller = null
      }
    }

    function connectionChanged(available) {
      if (!mounted) return
      abortRead()
      abortActivityRead()
      const activityWasConnected = activityLog.connected
      activityLog = recentActivityConnectionChanged(activityLog, available)
      activityNowMs = Date.now()
      if (available && !activityWasConnected && document.visibilityState === 'visible') {
        activityFailures = 0
        nextActivityPollAt = 0
        void refreshRecentActivity()
      }
      const previous = contextSnapshot.connected
      contextSnapshot = homeContextConnectionChanged(contextSnapshot, available)
      contextNowMs = Date.now()
      if (available && !previous && document.visibilityState === 'visible') {
        failures = 0
        nextPollAt = 0
        void refreshContext()
      }
    }

    function visibilityChanged() {
      if (!mounted) return
      abortRead()
      abortActivityRead()
      activityLog = invalidateRecentActivity(activityLog)
      activityNowMs = Date.now()
      if (document.visibilityState === 'visible' && activityLog.connected) {
        nextActivityPollAt = 0
        void refreshRecentActivity()
      }
      contextSnapshot = invalidateHomeContextRead(contextSnapshot)
      contextNowMs = Date.now()
      if (document.visibilityState === 'visible' && contextSnapshot.connected) {
        nextPollAt = 0
        void refreshContext()
      }
    }

    const unsubscribe = connected.subscribe(connectionChanged)
    document.addEventListener('visibilitychange', visibilityChanged)
    const ageTimer = window.setInterval(() => {
      contextNowMs = Date.now()
      activityNowMs = contextNowMs
    }, 1000)
    const pollTimer = window.setInterval(() => {
      if (!contextSnapshot.pending && contextSnapshot.connected &&
          document.visibilityState === 'visible' && Date.now() >= nextPollAt) void refreshContext()
      if (!activityLog.pending && activityLog.connected &&
          document.visibilityState === 'visible' && Date.now() >= nextActivityPollAt) void refreshRecentActivity()
    }, 15000)
    return () => {
      mounted = false
      abortRead()
      abortActivityRead()
      activityLog = invalidateRecentActivity(activityLog)
      unsubscribe()
      document.removeEventListener('visibilitychange', visibilityChanged)
      window.clearInterval(ageTimer)
      window.clearInterval(pollTimer)
    }
  })
</script>

<svelte:head>
  <title>Home · Quiet Atlas design review | HomeHub</title>
  <meta name="description" content="Read-only Quiet Atlas Home review with source-qualified HomeHub context and illustrative examples." />
</svelte:head>

<main class:daylight class="home-review" aria-label="Quiet Atlas Home design review">
  <header class="foreword">
    <div>
      <p class="eyebrow">HOME / OVERVIEW</p>
      <h1><span class="desktop-home-heading">Home</span><span class="mobile-home-heading">Home</span></h1>
      <p class="subhead">Reported context and quick access to your lights.</p>
    </div>
    <a class="apartment-link" href="/" aria-label="Open existing Apartment and household tools">
      <span class="icon-dot" aria-hidden="true"></span>
      Apartment & household tools <span aria-hidden="true">↗</span>
    </a>
  </header>

  <section class="phone-status" aria-label="Reported HomeHub status">
    <div class="phone-status-header">
      <span>HomeHub report</span>
      <strong class:unverified={contextDisplay.status !== 'recent'}>{contextDisplay.status === 'recent' ? 'Recent report' : 'Not verified'}</strong>
    </div>
    <div class="phone-status-grid">
      <div><span>HOUSE STATE</span><strong>{contextDisplay.house}</strong></div>
      <div><span>ACTIVITY</span><strong>{contextDisplay.activity}</strong></div>
    </div>
    <p>{contextDisplay.note}. A recent REST response is not proof of sensor freshness or room location.</p>
  </section>

  <section class="phone-actions" aria-labelledby="phone-lighting-title">
    <a class="phone-functional-handoff" href="/#apartment-controls">Adjust lights now <span aria-hidden="true">↗</span></a>
    <div class="phone-actions-head">
      <span class="eyebrow">Read-only preview</span>
      <h2 id="phone-lighting-title">Browse lighting</h2>
      <p>Open a room or explore scenes. These new Control screens are read-only design reviews, not light switches yet.</p>
    </div>
    <nav class="phone-rooms" aria-label="Browse lighting by room">
      {#each groups as group (group.id)}
        <a href={controlGroupHref(group.id)} class="phone-room" aria-label={group.label}>
          <span class="phone-room-icon" aria-hidden="true"></span>
          <span class="phone-room-copy"><strong>{group.name}</strong><small>{group.detail} · Browse fixtures</small></span>
          <span class="phone-room-arrow" aria-hidden="true">↗</span>
        </a>
      {/each}
    </nav>
    <a class="phone-scenes" href={CONTROL_SCENES_HREF}>
      <span><strong>Scenes &amp; presets</strong><small>Browse available names · no activation</small></span>
      <span aria-hidden="true">↗</span>
    </a>
  </section>

  <section class="phone-apartment-entry" aria-labelledby="phone-apartment-title">
    <span>THE APARTMENT / 02</span>
    <h2 id="phone-apartment-title">Your place, beyond the controls.</h2>
    <p>The detailed Apartment Canvas is being developed separately. Keep the current Apartment and household tools available while the physical view is refined.</p>
    <a href="/">Open Apartment &amp; household tools <span aria-hidden="true">↗</span></a>
  </section>

  <section class="apartment-stage" aria-labelledby="apartment-stage-title">
    <div class="world">
      <div class="ambient-orb" aria-hidden="true"></div>
      <div class="world-topline">
        <span>01 / THE APARTMENT</span>
        <span class="source">SPATIAL PLACEHOLDER · NOT A FLOOR PLAN</span>
      </div>
      <div class="world-bottom">
        <div class="readout">
          <span>HOUSE STATE</span>
          <strong>{contextDisplay.house}</strong>
        </div>
        <div class="readout">
          <span>ACTIVITY</span>
          <strong>{contextDisplay.activity}</strong>
        </div>
        <div class="world-note">{contextDisplay.note}</div>
      </div>
      <a class="working-lighting-link" href="/#apartment-controls">Adjust lights now <span aria-hidden="true">↗</span></a>
      <div class="world-message">
        <p class="world-kicker">Spatial study</p>
        <h2 id="apartment-stage-title">Apartment preview</h2>
        <p>Actual apartment geometry and its cinematic view will come from the separate, evidence-checked Apartment Canvas (#192).</p>
      </div>
    </div>
    <aside class="context-rail" aria-label="Source-qualified HomeHub context">
      {#if reviewExamples}
        <p class="rail-head">DESIGN EXAMPLES <span aria-hidden="true">—</span></p>
        <p class="rail-title">{example.title}</p>
        <p class="rail-description">{example.description}</p>
        <p class="rail-kind">{example.kind}</p>
        <label class="sample-label" for="sample-state">Illustrative context examples</label>
        <select id="sample-state" bind:value={sampleState}>
          <option value="unavailable">Unavailable</option>
          <option value="stale">Stale light reading</option>
          <option value="empty">Empty history</option>
          <option value="attention">Manual ownership</option>
        </select>
      {:else}
        <p class="rail-head">HOMEHUB CONTEXT <span aria-hidden="true">—</span></p>
        {#if contextDisplay.status === 'recent'}
          <p class="rail-title">HomeHub reports {contextDisplay.house}</p>
          <p class="rail-description">Reported Activity: {contextDisplay.activity}</p>
          <p class="rail-kind">RECENT REST REPORT</p>
        {:else}
          <p class="rail-title">Current context not verified</p>
          <p class="rail-description">{contextDisplay.note}</p>
          <p class="rail-kind">NO RECENT VERIFIED REPORT</p>
        {/if}
        <p class="rail-provenance">A REST response is not sensor freshness or room-location evidence.</p>
      {/if}
      <button class="review-toggle" type="button" aria-pressed={reviewExamples} on:click={() => (reviewExamples = !reviewExamples)}>
        {reviewExamples ? 'Return to HomeHub report' : 'Review illustrative states'}
      </button>
      <a class="rail-footer" href="/quiet-atlas/insights">View Insights <span aria-hidden="true">↗</span></a>
    </aside>
  </section>

  <section class="lighting-dock" aria-labelledby="lighting-title">
    <div class="dock-head">
      <div>
        <p class="eyebrow">THE EVERYDAY CONTROLS</p>
        <h2 id="lighting-title">Browse lighting</h2>
      </div>
      <a class="browse-link" href="/quiet-atlas/control">Open Control review <span aria-hidden="true">↗</span></a>
    </div>
    <div class="groups" aria-label="Browse lighting groups">
      {#each groups as group}
        <a href={controlGroupHref(group.id)} class="group" aria-label={group.label}>
          <span class="group-mark" aria-hidden="true"></span>
          <span class="group-copy"><strong>{group.name}</strong><small>{group.detail} · view lights</small></span>
          <span class="group-arrow" aria-hidden="true">↗</span>
        </a>
      {/each}
    </div>
    <div class="scene-line">
      <span><strong>Scenes & presets</strong><small>Browse names from the existing read-only lighting review; no sample scenes are activated.</small></span>
      <a href={CONTROL_SCENES_HREF}>Browse scenes <span aria-hidden="true">↗</span></a>
    </div>
  </section>

  <QuietAtlasEnvironment />

  <section class="recent-log" aria-labelledby="recent-log-title">
    <div class="recent-log-head">
      <div>
        <p class="eyebrow">RECORDED / RECENT</p>
        <h2 id="recent-log-title">What HomeHub logged.</h2>
      </div>
      <span>Last 24 hours · read-only</span>
    </div>
    {#if recentActivity.status === 'recent'}
      <ol class="recent-log-events" aria-label="Recent recorded activities">
        {#each recentActivity.items as entry (entry.key)}
          <li>
            <strong>{entry.label}</strong>
            <time datetime={new Date(entry.timestamp).toISOString()}>{recentActivityTime(entry.timestamp)}</time>
          </li>
        {/each}
      </ol>
    {:else}
      <p class="recent-log-status" role="status">{recentActivity.message}</p>
    {/if}
    <p class="recent-log-note">Event history, not confirmation of a person's presence, room, or current House State. Dates and times use this device's timezone.
      <a href="/quiet-atlas/insights">View Insights ↗</a>
    </p>
  </section>

  <section class="mobile-context" aria-label="HomeHub context and review">
    {#if reviewExamples}
      <span class="mobile-context-kind">DESIGN EXAMPLE · {example.kind}</span>
      <p><strong>{example.title}</strong> — {example.description}</p>
      <label for="mobile-review-state">Review example state</label>
      <select id="mobile-review-state" bind:value={sampleState}>
        <option value="unavailable">Unavailable</option>
        <option value="stale">Stale light reading</option>
        <option value="empty">Empty history</option>
        <option value="attention">Manual ownership</option>
      </select>
    {:else}
      <span class="mobile-context-kind">HOMEHUB CONTEXT</span>
      {#if contextDisplay.status === 'recent'}
        <p><strong>{contextDisplay.house}</strong> · Reported Activity: {contextDisplay.activity}. {contextDisplay.note}.</p>
      {:else}
        <p><strong>Context not verified.</strong> {contextDisplay.note}.</p>
      {/if}
    {/if}
    <button class="review-toggle" type="button" aria-pressed={reviewExamples} on:click={() => (reviewExamples = !reviewExamples)}>
      {reviewExamples ? 'Return to HomeHub report' : 'Review illustrative states'}
    </button>
    <a href="/quiet-atlas/insights">Open Insights ↗</a>
  </section>

  <details class="preview-options">
    <summary>Preview appearance and source notes</summary>
  <div class="preview-ribbon">
    <span class="brand">QUIET ATLAS <span class="multiply">×</span> DAYLIGHT</span>
    <span class="disclaimer">Read-only review · context is HomeHub-reported; examples are illustrative</span>
    <button
      class="theme-toggle"
      type="button"
      on:click={() => (daylight = !daylight)}
      aria-label={daylight ? 'Use night preview' : 'Use day preview'}
      aria-pressed={daylight}
    >{daylight ? 'Night view' : 'Day view'}</button>
  </div>
  </details>

  <footer class="review-footer">
    <span>This route never sends lighting or scene commands.</span>
    <a href="/quiet-atlas">Back to lighting preview</a>
  </footer>
</main>

<style>
  .home-review {
    --bg: #101a15;
    --stage: #1a2a21;
    --deep: #0f211b;
    --line: rgba(224,235,214,.14);
    --ink: #f7f3e8;
    --muted: #b4c6b5;
    --gold: #edcfa0;
    --glow: rgba(155,179,117,.24);
    color: var(--ink);
    background: radial-gradient(ellipse at 72% 12%,rgba(178,154,104,.09),transparent 50%),var(--bg);
    padding: 28px clamp(19px,4vw,64px) 26px;
    min-height: 100%;
    font-family: system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  }
  .home-review.daylight {
    --bg:#eeeee6; --stage:#e0e5d8; --deep:#d5dfd3; --line:rgba(45,77,55,.18);
    --ink:#263a2d; --muted:#5b6d5f; --gold:#805f37; --glow:rgba(177,152,112,.14);
  }
  .mobile-home-heading,.phone-status,.phone-actions,.phone-apartment-entry {display:none;}
  button,select { font:inherit; }
  button, a, select { -webkit-tap-highlight-color:transparent; }
  a { color:inherit;text-decoration:none; }
  a:focus-visible,button:focus-visible,select:focus-visible { outline:3px solid var(--gold);outline-offset:3px; }
  .preview-ribbon { display:flex;align-items:center;gap:14px;flex-wrap:wrap;min-height:28px;color:var(--muted);font-size:14px; }
  .brand {font-size:14px;font-weight:800;letter-spacing:.13em;color:var(--gold);}
  .multiply {color:var(--muted);margin:0 5px;}
  .disclaimer {flex:1;min-width:190px;}
  .theme-toggle {background:transparent;border:1px solid var(--line);border-radius:99px;color:var(--ink);padding:7px 14px;cursor:pointer;}
  .foreword {display:flex;align-items:end;justify-content:space-between;gap:16px;margin:24px 0 23px;}
  .eyebrow,.world-kicker {font-size:14px;letter-spacing:.14em;font-weight:750;color:var(--gold);margin:0 0 9px;}
  h1,h2,p {margin-top:0;}
  h1 {font-size:clamp(29px,3.2vw,43px);font-weight:610;letter-spacing:-.045em;line-height:1.13;margin-bottom:7px;}
  .subhead {font-size:14px;color:var(--muted);margin:0;}
  .apartment-link {display:inline-flex;align-items:center;gap:10px;border:1px solid var(--line);padding:12px 16px;border-radius:100px;font-size:14px;white-space:nowrap;min-height:44px;}
  .icon-dot {width:8px;height:8px;border:1px solid var(--gold);transform:rotate(45deg);}
  .apartment-stage {display:grid;grid-template-columns:minmax(0,1fr) minmax(235px,280px);border:1px solid var(--line);border-radius:19px;overflow:hidden;min-height:300px;}
  .world {position:relative;min-width:0;overflow:hidden;background:radial-gradient(ellipse at 47% 45%,var(--glow),transparent 53%),linear-gradient(130deg,var(--stage),var(--deep));padding:22px 27px;display:flex;flex-direction:column;justify-content:space-between;isolation:isolate;}
  .ambient-orb {position:absolute;width:390px;height:390px;right:4%;top:-19%;z-index:-1;border-radius:50%;background:radial-gradient(circle at 45% 46%,rgba(237,207,160,.15),rgba(98,151,115,.07) 42%,transparent 69%);filter:blur(8px);pointer-events:none;}
  .world-topline {display:flex;align-items:center;justify-content:space-between;gap:10px;color:var(--muted);font-size:14px;letter-spacing:.1em;}
  .world-topline .source {font-size:14px;text-align:right;}
  .world-message {max-width:540px;margin:18px 0;}
  .world-message h2 {font-size:24px;line-height:1.13;font-weight:570;letter-spacing:-.04em;margin:0 0 13px;}
  .world-message>p:last-child {color:var(--muted);font-size:14px;line-height:1.6;max-width:430px;margin:0;}
  .world-bottom {display:flex;align-items:end;gap:21px;flex-wrap:wrap;}
  .readout {display:flex;flex-direction:column;gap:7px;min-width:124px;}
  .readout span {font-size:14px;letter-spacing:.13em;color:var(--muted);}
  .readout strong {font-size:28px;font-weight:600;}
  .world-note {font-size:14px;color:var(--muted);margin-left:auto;max-width:210px;line-height:1.4;}
  .context-rail {border-left:1px solid var(--line);background:color-mix(in srgb,var(--stage) 80%,var(--bg));padding:25px 22px 20px;display:flex;flex-direction:column;}
  .rail-head {font-size:14px;letter-spacing:.14em;color:var(--gold);font-weight:750;display:flex;justify-content:space-between;}
  .rail-title {font-size:20px;font-weight:600;letter-spacing:-.025em;line-height:1.2;margin:12px 0 10px;}
  .rail-description {font-size:14px;line-height:1.55;color:var(--muted);}
  .rail-kind {font-size:14px;color:var(--gold);margin-bottom:24px;}
  .sample-label {font-size:14px;color:var(--muted);margin-top:auto;margin-bottom:8px;}
  .rail-provenance {font-size:14px;line-height:1.5;color:var(--muted);margin-top:auto;}
  .review-toggle {display:inline-flex;align-items:center;justify-content:center;min-height:44px;margin-top:12px;padding:8px 12px;border:1px solid var(--line);border-radius:9px;background:transparent;color:var(--gold);text-align:center;cursor:pointer;font-size:14px;}
  .context-rail select {padding:9px;background:var(--deep);border:1px solid var(--line);border-radius:7px;color:var(--ink);width:100%;min-height:44px;}
  .rail-footer {display:flex;justify-content:space-between;border-top:1px solid var(--line);padding-top:14px;margin-top:18px;font-size:14px;}
  .lighting-dock {margin-top:25px;}
  .dock-head {display:flex;align-items:end;justify-content:space-between;gap:14px;margin-bottom:14px;}
  .dock-head h2 {font-size:23px;letter-spacing:-.035em;margin:0;font-weight:600;}
  .browse-link {font-size:14px;color:var(--gold);padding:9px 0;}
  .groups {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;}
  .group {display:flex;align-items:center;gap:10px;min-width:0;min-height:76px;background:linear-gradient(145deg,var(--stage),var(--deep));border:1px solid var(--line);border-radius:11px;padding:12px 13px;}
  .group:hover,.apartment-link:hover {border-color:var(--gold);}
  .group-mark {width:10px;height:10px;border:2px solid var(--gold);border-radius:50%;flex:0 0 auto;opacity:.85;}
  .group-copy {display:flex;flex-direction:column;min-width:0;gap:4px;}
  .group-copy strong {font-size:14px;font-weight:600;white-space:nowrap;}
  .group-copy small {font-size:14px;color:var(--muted);white-space:nowrap;}
  .group-arrow {margin-left:auto;color:var(--muted);font-size:14px;}
  .scene-line {display:flex;align-items:center;justify-content:space-between;gap:12px;padding:13px 2px;border-bottom:1px solid var(--line);}
  .scene-line>span {display:flex;flex-direction:column;gap:5px;}
  .scene-line strong {font-size:14px;}
  .scene-line small {font-size:14px;color:var(--muted);line-height:1.4;}
  .scene-line a {color:var(--gold);white-space:nowrap;font-size:14px;padding:10px 0;}
  .recent-log{margin-top:24px;padding:20px 23px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);}
  .recent-log-head{display:flex;justify-content:space-between;align-items:end;gap:16px;flex-wrap:wrap;}
  .recent-log-head h2{font-size:22px;font-weight:600;letter-spacing:-.03em;margin:0;}
  .recent-log-head>span{font-size:14px;color:var(--muted);}
  .recent-log-events{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));list-style:none;margin:16px 0 9px;padding:0;gap:8px;}
  .recent-log-events li{display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;border-left:2px solid var(--gold);padding:6px 12px;min-width:0;}
  .recent-log-events strong{font-size:14px;font-weight:600;}
  .recent-log-events time{color:var(--muted);font-size:14px;}
  .recent-log-status{font-size:14px;margin:16px 0 9px;color:var(--muted);}
  .recent-log-note{font-size:14px;color:var(--muted);margin:10px 0 0;line-height:1.5;}
  .recent-log-note a{color:var(--gold);text-decoration:underline;margin-left:10px;}
  .mobile-context {display:none;}
  .review-footer {display:flex;gap:10px;justify-content:space-between;flex-wrap:wrap;font-size:14px;color:var(--muted);margin-top:23px;}
  .review-footer a {text-decoration:underline;}
  @media (max-width:960px) {
    .apartment-stage {grid-template-columns:minmax(0,1fr) 210px;}
    .world-note {max-width:100%;}
    .group {padding:10px;gap:7px;}
    .group-copy small {font-size:14px;}
  }
  @media (max-width:700px) {
    .recent-log{padding:17px 4px;margin-top:16px;}
    .recent-log-head h2{font-size:19px;}
    .recent-log-events{grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;}
    .recent-log-events li{padding:6px 10px;}
    .recent-log-note a{display:inline-block;margin:7px 0 0;}
    .home-review {padding:14px 13px 16px;}
    .preview-ribbon {gap:8px;font-size:14px;}
    .brand {font-size:14px;}
    .disclaimer {flex-basis:calc(100% - 105px);min-width:0;line-height:1.25;}
    .theme-toggle {padding:5px 9px;font-size:14px;}
    .foreword {display:block;margin:14px 0 13px;}
    .eyebrow {font-size:14px;margin-bottom:6px;}
    h1 {font-size:29px;margin-bottom:4px;}
    .subhead {font-size:14px;}
    .apartment-link {display:none;}
    .apartment-stage {display:block;min-height:0;border-radius:14px;}
    .world {min-height:237px;padding:13px 15px 15px;}
    .world-topline {font-size:14px;}
    .world-topline .source {font-size:8px;max-width:136px;}
    .ambient-orb {width:250px;height:250px;top:-10%;}
    .world-message {margin:18px 0 17px;}
    .world-message h2 {font-size:25px;max-width:340px;margin-bottom:8px;}
    .world-message>p:last-child {font-size:14px;line-height:1.45;max-width:310px;}
    .world-bottom {gap:18px;}
    .readout {min-width:0;flex:1;gap:4px;}
    .readout span {font-size:8px;}
    .readout strong {font-size:14px;}
    .world-note {flex-basis:100%;margin-left:0;font-size:14px;line-height:1.25;}
    .context-rail {display:none;}
    .lighting-dock {margin-top:14px;}
    .dock-head {margin-bottom:9px;}
    .dock-head h2 {font-size:20px;}
    .browse-link {font-size:14px;}
    .groups {grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;}
    .group {min-height:56px;border-radius:9px;padding:8px 10px;gap:9px;}
    .group-copy strong {font-size:14px;}
    .group-copy small {font-size:14px;}
    .scene-line {padding:10px 2px;}
    .scene-line strong {font-size:14px;}
    .scene-line small {font-size:14px;max-width:250px;}
    .scene-line a {font-size:14px;}
    .mobile-context {display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:13px;border-top:1px solid var(--line);padding-top:11px;font-size:14px;color:var(--muted);}
    .mobile-context-kind {font-size:14px;color:var(--gold);letter-spacing:.07em;text-transform:uppercase;}
    .mobile-context p {flex-basis:100%;line-height:1.45;margin:0;}
    .mobile-context strong {color:var(--ink);}
    .mobile-context label {font-size:14px;}
    .mobile-context select {min-height:34px;max-width:145px;min-width:0;flex:1;border:1px solid var(--line);border-radius:6px;color:var(--ink);background:var(--stage);padding:5px;}
    .mobile-context a {margin-left:auto;color:var(--gold);}
    .mobile-context .review-toggle {margin-top:0;font-size:14px;flex:0 0 auto;}
    .review-footer {font-size:14px;margin-top:14px;}
    /* Phone has its own information hierarchy, not a scaled desktop stage. */
    .desktop-home-heading {display:none;}
    .mobile-home-heading {display:inline;}
    .phone-status,.phone-actions,.phone-apartment-entry {display:block;min-width:0;}
    .apartment-stage,.lighting-dock {display:none;}
    .foreword {margin:18px 0 16px;}
    .foreword h1 {font-size:clamp(30px,8vw,38px);line-height:1.12;}
    .foreword .subhead {font-size:14px;line-height:1.45;}
    .phone-status {border:1px solid var(--line);border-radius:16px;background:linear-gradient(135deg,var(--stage),var(--deep));padding:15px;margin-bottom:20px;}
    .phone-status-header {display:flex;align-items:center;justify-content:space-between;gap:10px;color:var(--gold);font-size:14px;font-weight:700;letter-spacing:.08em;}
    .phone-status-header strong {font-size:14px;letter-spacing:0;text-align:right;color:var(--muted);}
    .phone-status-header .unverified {color:var(--gold);}
    .phone-status-grid {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px;margin:15px 0 11px;}
    .phone-status-grid>div {min-width:0;display:flex;flex-direction:column;gap:6px;}
    .phone-status-grid>div+div {border-left:1px solid var(--line);padding-left:14px;}
    .phone-status-grid span {font-size:14px;letter-spacing:.09em;color:var(--muted);}
    .phone-status-grid strong {font-size:18px;line-height:1.25;font-weight:650;overflow-wrap:anywhere;}
    .phone-status p {font-size:14px;color:var(--muted);line-height:1.55;margin:0;}
    .phone-actions {margin-bottom:20px;}
    .phone-actions-head .eyebrow {font-size:14px;margin:0 0 8px;}
    .phone-actions-head h2 {font-size:27px;font-weight:590;line-height:1.12;margin:0 0 8px;}
    .phone-actions-head p {font-size:14px;color:var(--muted);line-height:1.55;margin:0 0 14px;}
    .phone-rooms {display:grid;grid-template-columns:minmax(0,1fr);gap:9px;}
    .phone-room {display:flex;align-items:center;gap:15px;min-height:76px;box-sizing:border-box;min-width:0;padding:10px 15px;border-radius:14px;border:1px solid var(--line);background:linear-gradient(115deg,var(--stage),var(--deep));}
    .phone-room-icon {width:16px;height:16px;flex:0 0 16px;border:2px solid var(--gold);border-radius:5px;transform:rotate(45deg);}
    .phone-room-copy {display:flex;flex-direction:column;gap:5px;min-width:0;flex:1;}
    .phone-room-copy strong {font-size:16px;font-weight:640;line-height:1.15;}
    .phone-room-copy small {font-size:14px;line-height:1.35;color:var(--muted);white-space:normal;}
    .phone-room-arrow {color:var(--gold);font-size:21px;flex:0 0 auto;}
    .phone-scenes {min-height:64px;box-sizing:border-box;display:flex;align-items:center;justify-content:space-between;gap:13px;margin-top:11px;padding:11px 15px;border:1px solid var(--line);border-radius:14px;background:rgba(210,183,136,.07);}
    .phone-scenes>span:first-child {display:flex;flex-direction:column;gap:5px;min-width:0;}
    .phone-scenes strong {font-size:16px;font-weight:640;}
    .phone-scenes small {font-size:14px;color:var(--muted);line-height:1.4;}
    .phone-scenes>span:last-child {color:var(--gold);font-size:21px;}
    .phone-functional-handoff {min-height:50px;box-sizing:border-box;display:flex;align-items:center;justify-content:space-between;gap:10px;padding:9px 2px;border-bottom:1px solid var(--line);color:var(--gold);font-size:14px;font-weight:650;}
    .phone-apartment-entry {padding:21px 16px;margin-bottom:18px;border:1px solid var(--line);border-radius:16px;background:radial-gradient(ellipse at 95% -10%,var(--glow),transparent 70%),var(--deep);}
    .phone-apartment-entry>span {font-size:14px;font-weight:700;color:var(--gold);letter-spacing:.13em;}
    .phone-apartment-entry h2 {font-size:23px;font-weight:560;line-height:1.2;margin:10px 0;}
    .phone-apartment-entry p {font-size:14px;line-height:1.6;color:var(--muted);margin-bottom:12px;}
    .phone-apartment-entry a {min-height:48px;display:flex;align-items:center;justify-content:space-between;gap:12px;color:var(--gold);font-size:14px;font-weight:650;border-top:1px solid var(--line);padding-top:11px;}
    /* Even secondary review controls must remain usable by touch. */
    .theme-toggle {min-height:44px;font-size:14px;padding:9px 12px;}
    .mobile-context select {min-height:44px;font-size:14px;}
    .mobile-context .review-toggle {min-height:44px;font-size:14px;}
    .mobile-context a {min-height:44px;display:inline-flex;align-items:center;font-size:14px;}
    .review-footer {font-size:14px;line-height:1.5;}
  }
  @media (max-width:360px) {
    .foreword {margin:9px 0 8px;}
    .world-message {margin:10px 0;}
    .world-message h2 {font-size:22px;margin-bottom:6px;}
    .world {min-height:194px;padding:10px 13px 11px;}
    .world-bottom {gap:8px;}
    .world-note {line-height:1.2;}
    .lighting-dock {margin-top:9px;}
    .browse-link {max-width:90px;text-align:right;}
    .group-arrow {display:none;}
    .scene-line small {max-width:165px;}
  }
  .working-lighting-link,.phone-functional-handoff {display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:52px;box-sizing:border-box;padding:12px 18px;margin:16px 0;border:1px solid var(--gold);border-radius:12px;background:var(--ink);color:var(--bg);font-size:15px;font-weight:650;}
  .home-review {min-width:0;overflow-wrap:anywhere;}
  .rail-footer,.browse-link,.scene-line a,.review-footer a {min-height:44px;display:inline-flex;align-items:center;}
  .group-copy small {white-space:normal;}
  @media (prefers-reduced-motion:reduce) {
    .home-review * {transition:none!important;animation:none!important;}
  }

  .preview-options { margin-top:24px; padding-top:12px; border-top:1px solid rgba(210,225,207,.15); }
  .preview-options summary { min-height:44px; display:inline-flex; align-items:center; cursor:pointer; color:#bccbbf; font-size:14px; }
  .preview-options summary:focus-visible { outline:3px solid #d5e7bd; outline-offset:3px; }
  .preview-options .preview-ribbon { margin-top:12px; }
</style>
