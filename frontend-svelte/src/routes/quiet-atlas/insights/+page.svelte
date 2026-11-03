<script>
  // #270 Insights review: only recorded activity has a live source here.
  // A logged activity is not a current activity, presence, room, or causal trace.
  import { onMount } from 'svelte'
  import { connected } from '$lib/stores/connection.js'
  import InsightsContextReadout from '$lib/components/InsightsContextReadout.svelte'
  import {
    newRecentActivityLog, recentActivityConnectionChanged, invalidateRecentActivity,
    beginRecentActivityRead, acceptRecentActivityRead, failRecentActivityRead,
    recentActivityPresentation, recentActivityTime,
  } from '$lib/quietAtlas/recentActivityLog.js'

  let activityLog = newRecentActivityLog()
  let nowMs = 0
  let studyOpen = false
  $: activity = recentActivityPresentation(activityLog, nowMs)

  onMount(() => {
    let mounted = true
    /** @type {AbortController | null} */
    let controller = null
    let failures = 0
    let nextPollAt = 0

    function abortRead() {
      controller?.abort()
      controller = null
    }

    async function refresh() {
      if (!mounted || !activityLog.connected || document.visibilityState !== 'visible') return
      const next = beginRecentActivityRead(activityLog)
      activityLog = next.state
      if (!next.ticket) return
      const ticket = next.ticket
      controller = new AbortController()
      const currentController = controller
      const timeout = window.setTimeout(() => currentController.abort(), 8000)
      nextPollAt = Date.now() + 60000
      try {
        const response = await fetch('/api/events/activity?days=1&limit=6&offset=0', {
          signal: currentController.signal, cache: 'no-store',
        })
        if (!response.ok) throw new Error('Activity history unavailable')
        const body = await response.json()
        if (!mounted) return
        const accepted = acceptRecentActivityRead(activityLog, ticket, body, Date.now())
        if (accepted !== activityLog) {
          activityLog = accepted
          nowMs = Date.now()
          failures = accepted.failed ? Math.min(3, failures + 1) : 0
          nextPollAt = nowMs + (accepted.failed ? 30000 * failures : 60000)
        }
      } catch {
        if (!mounted) return
        const failed = failRecentActivityRead(activityLog, ticket)
        if (failed !== activityLog) {
          activityLog = failed
          nowMs = Date.now()
          failures = Math.min(3, failures + 1)
          nextPollAt = nowMs + Math.min(120000, 30000 * failures)
        }
      } finally {
        window.clearTimeout(timeout)
        if (controller === currentController) controller = null
      }
    }

    function connectionChanged(available) {
      if (!mounted) return
      abortRead()
      const wasConnected = activityLog.connected
      activityLog = recentActivityConnectionChanged(activityLog, available)
      nowMs = Date.now()
      if (available && !wasConnected && document.visibilityState === 'visible') {
        failures = 0
        nextPollAt = 0
        void refresh()
      }
    }

    function visibilityChanged() {
      if (!mounted) return
      abortRead()
      activityLog = invalidateRecentActivity(activityLog)
      nowMs = Date.now()
      if (document.visibilityState === 'visible' && activityLog.connected) {
        nextPollAt = 0
        void refresh()
      }
    }

    const unsubscribe = connected.subscribe(connectionChanged)
    document.addEventListener('visibilitychange', visibilityChanged)
    const ageTimer = window.setInterval(() => { nowMs = Date.now() }, 1000)
    const pollTimer = window.setInterval(() => {
      if (!activityLog.pending && activityLog.connected &&
          document.visibilityState === 'visible' && Date.now() >= nextPollAt) void refresh()
    }, 15000)

    return () => {
      mounted = false
      abortRead()
      activityLog = invalidateRecentActivity(activityLog)
      unsubscribe()
      document.removeEventListener('visibilitychange', visibilityChanged)
      window.clearInterval(ageTimer)
      window.clearInterval(pollTimer)
    }
  })
</script>

<svelte:head>
  <title>Insights · Quiet Atlas design review | HomeHub</title>
  <meta name="description" content="Read-only source-qualified activity evidence in the Quiet Atlas Insights design study." />
</svelte:head>

<main class="insights-review" aria-label="Quiet Atlas Insights design review">
  <div class="review-top">
    <span>QUIET ATLAS <span class="cross">×</span> INSIGHTS</span>
    <span>Read-only design review</span>
  </div>

  <header class="insights-hero">
    <p class="eyebrow">THE HOUSE, EXPLAINED WITH CARE</p>
    <h1>Follow the evidence.<br /><em>Not the guesswork.</em></h1>
    <p class="intro">HomeHub makes decisions from signals. This Insights study separates HomeHub's current <strong>REST-reported context</strong> from recorded history. Neither report reconstructs sensor inputs, confidence, or reasons for automation decisions.</p>
  </header>

  <InsightsContextReadout />

  <div class="insights-grid">
    <section class="record" aria-labelledby="record-title">
      <header class="section-head">
        <div>
          <p class="eyebrow">01 / SOURCE-QUALIFIED RECORD</p>
          <h2 id="record-title">Recent activity</h2>
        </div>
        <span class="source-tag">GET · LAST 24 HOURS</span>
      </header>
      <p class="description">Recorded activity categories from HomeHub's event history. Receipt freshness applies to this request, not to the underlying sensors or current activity.</p>

      {#if activity.status === 'recent'}
        <ol class="event-rail" aria-label="Recent recorded activities">
          {#each activity.items as item (item.key)}
            <li class="event">
              <span class="event-node" aria-hidden="true"></span>
              <div>
                <strong>{item.label}</strong>
                <span>Recorded activity</span>
              </div>
              <time datetime={new Date(item.timestamp).toISOString()}>{recentActivityTime(item.timestamp)}</time>
            </li>
          {/each}
        </ol>
      {:else}
        <div class="event-fallback" role="status">
          <span class="fallback-symbol" aria-hidden="true">◌</span>
          <strong>{activity.message}</strong>
          <span>{activity.status === 'empty' ? 'A verified empty event page is not a connection error.' : 'No activity is displayed without a recent, valid report.'}</span>
        </div>
      {/if}
      <p class="source-note">Source: <code>GET /api/events/activity</code> · Event history is not confirmation of a person, room, current House State, or automation cause. Dates and times use this device's timezone.</p>
    </section>

    <aside class="mechanism" aria-labelledby="mechanism-title">
      <p class="eyebrow">02 / BEYOND THE RECORD</p>
      <h2 id="mechanism-title">Inside the decision</h2>
      <button
        type="button"
        class="phone-study-toggle"
        aria-controls="insights-study-content"
        aria-expanded={studyOpen}
        on:click={() => studyOpen = !studyOpen}
      >
        <span>{studyOpen ? 'Hide explanation layers' : 'Explore explanation layers'}</span>
        <span aria-hidden="true">{studyOpen ? '−' : '+'}</span>
      </button>
      <div id="insights-study-content" class="study-content" class:phone-collapsed={!studyOpen}>
      <p class="mechanism-intro">The future Insights instrument should connect evidence to interpretation and action. Those links are <strong>not source-qualified in this preview</strong>.</p>
      <div class="stages" aria-label="Proposed explanation layers, not live decision trace">
        <div class="stage">
          <span class="stage-id">EVIDENCE</span>
          <strong>What was observed?</strong>
          <p>Individual sensor inputs need fresh provenance before they can be displayed here.</p>
        </div>
        <div class="stage">
          <span class="stage-id">INTERPRETATION</span>
          <strong>Why that state?</strong>
          <p>Fusion, confidence and competing explanations are not reconstructed from activity logs.</p>
        </div>
        <div class="stage">
          <span class="stage-id">OUTCOME</span>
          <strong>What actually changed?</strong>
          <p>Lighting and automation effects need separate verified output evidence.</p>
        </div>
      </div>
      </div>
      <a class="existing-link" href="/analytics?shell=quiet-atlas">
        Open existing Analytics tools <span aria-hidden="true">↗</span>
      </a>
      <p class="mechanism-note">The existing tools remain available. This isolated study does not replace them or claim its explanatory layers are live.</p>
    </aside>
  </div>

  <footer class="review-footer">
    <span>DESIGN STUDY · NOT A LIVE FUSION OR DECISION TRACE</span>
    <a href="/quiet-atlas/home">Return to Home <span aria-hidden="true">↗</span></a>
  </footer>
</main>

<style>
  .insights-review {
    --ink: #e8ece3; --muted: #a6b9aa; --line: rgba(201,218,200,.17);
    --gold: #e8cda0; --deep: #101b15;
    min-height: 100%; padding: clamp(18px,3vw,36px) clamp(16px,4vw,52px) 48px;
    color: var(--ink); background: radial-gradient(ellipse at 84% 0%,rgba(90,128,91,.17),transparent 43%),var(--deep);
    font-family: system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  }
  .review-top {display:flex;justify-content:space-between;align-items:center;gap:12px;padding-bottom:17px;border-bottom:1px solid var(--line);color:var(--gold);font-size:10px;letter-spacing:.15em;font-weight:750;}
  .review-top > :last-child {color:var(--muted);letter-spacing:.04em;font-weight:450;}
  .cross {color:#87a68a;}
  .insights-hero {max-width:850px;padding:clamp(35px,6vw,74px) 0 clamp(28px,4vw,52px);}
  .eyebrow {color:#aec2af;font-size:10px;font-weight:700;letter-spacing:.17em;margin:0 0 17px;}
  h1,h2 {font-family:Georgia,"Times New Roman",serif;font-weight:400;}
  h1 {font-size:clamp(37px,5.2vw,76px);line-height:1.12;letter-spacing:-.045em;margin:0;}
  h1 em {color:var(--gold);font-weight:400;}
  .intro {max-width:660px;color:#bfcec0;font-size:clamp(13px,1.4vw,16px);line-height:1.75;margin:22px 0 0;}
  .intro strong {color:#f1e4c9;font-weight:550;}
  .insights-grid {display:grid;grid-template-columns:minmax(0,1.4fr) minmax(280px,.82fr);gap:clamp(16px,2vw,28px);align-items:start;max-width:1460px;}
  .record,.mechanism {min-width:0;border-top:1px solid var(--line);padding-top:24px;}
  .section-head {display:flex;align-items:flex-end;justify-content:space-between;gap:16px;}
  .section-head .eyebrow {margin-bottom:11px;}
  h2 {margin:0;font-size:clamp(28px,3.2vw,42px);letter-spacing:-.025em;}
  .source-tag {font-size:10px;color:var(--gold);white-space:nowrap;letter-spacing:.06em;padding-bottom:4px;}
  .description,.mechanism-intro {max-width:620px;color:var(--muted);font-size:13px;line-height:1.7;margin:16px 0 23px;}
  .mechanism-intro strong {color:#ead7b6;font-weight:550;}
  .event-rail {list-style:none;margin:0;padding:0 0 0 10px;border-left:1px solid rgba(164,195,164,.38);}
  .event {display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;position:relative;margin:0 0 0 0;padding:18px 0 18px 25px;border-bottom:1px solid var(--line);}
  .event-node {position:absolute;left:-15px;top:24px;width:9px;height:9px;border-radius:50%;border:2px solid #d1bd8f;background:#344e38;}
  .event div {display:flex;flex-direction:column;gap:5px;min-width:0;}
  .event strong {font-size:18px;font-weight:550;color:var(--ink);}
  .event div span {font-size:11px;color:var(--muted);}
  .event time {font-size:11px;color:var(--gold);font-variant-numeric:tabular-nums;text-align:right;align-self:start;line-height:1.5;}
  .event-fallback {min-height:165px;padding:24px;border:1px solid var(--line);display:flex;flex-direction:column;justify-content:center;align-items:flex-start;gap:8px;background:rgba(178,207,175,.035);}
  .fallback-symbol {font-size:28px;color:var(--gold);}
  .event-fallback strong {font-size:17px;font-weight:550;}
  .event-fallback span:last-child {font-size:12px;line-height:1.6;color:var(--muted);}
  .source-note {font-size:11px;color:#a5b8a8;line-height:1.7;border-top:1px solid var(--line);margin:30px 0 0;padding-top:18px;}
  code {color:#d3ddb9;overflow-wrap:anywhere;}
  .stages {border-left:1px solid var(--line);margin:26px 0 0;}
  .stage {position:relative;padding:0 0 23px 22px;margin:0;}
  .stage::before {content:"";position:absolute;left:-4px;top:6px;width:7px;height:7px;border-radius:50%;background:#779478;}
  .stage-id {display:block;color:var(--gold);letter-spacing:.13em;font-size:9px;font-weight:700;margin:0 0 8px;}
  .stage strong {display:block;font-size:15px;font-weight:570;color:var(--ink);}
  .stage p {color:var(--muted);font-size:12px;line-height:1.65;margin:7px 0 0;}
  .existing-link {display:flex;gap:12px;justify-content:space-between;align-items:center;min-height:46px;padding:12px 14px;border:1px solid rgba(214,183,128,.45);border-radius:8px;color:#f5ddad;text-decoration:none;font-size:13px;}
  .existing-link:hover {background:rgba(214,183,128,.07);}
  .existing-link:focus-visible,.review-footer a:focus-visible {outline:3px solid #f1d499;outline-offset:4px;}
  .mechanism-note {font-size:11px;line-height:1.6;color:var(--muted);margin:14px 0 0;}
  .review-footer {display:flex;justify-content:space-between;gap:16px;border-top:1px solid var(--line);margin:52px 0 0;padding-top:20px;font-size:10px;letter-spacing:.08em;color:var(--muted);}
  .review-footer a {font-size:12px;letter-spacing:0;color:var(--gold);}
  @media(max-width:880px){.insights-grid{grid-template-columns:minmax(0,1fr)}.record,.mechanism{padding-top:20px}.mechanism{margin-top:18px}.insights-hero{padding:42px 0 30px}}
  @media(max-width:480px){.review-top{flex-wrap:wrap;line-height:1.6}.insights-review{padding:18px 16px 36px}.source-tag{font-size:9px}.section-head{align-items:start}.event{grid-template-columns:minmax(0,1fr);gap:8px}.event time{text-align:left}.review-footer{flex-direction:column}.insights-hero{padding:34px 0 30px}}
  .phone-study-toggle {display:none;}
  @media(max-width:480px){
    .insights-review {padding:14px 15px calc(36px + env(safe-area-inset-bottom, 0px));}
    .review-top {font-size:9px;letter-spacing:.08em;gap:8px;padding-bottom:12px;}
    .insights-hero {padding:21px 0 18px;}
    .insights-hero .eyebrow {font-size:10px;margin-bottom:10px;}
    h1 {font-size:clamp(30px,8.8vw,38px);line-height:1.14;letter-spacing:-.035em;}
    .intro {font-size:12px;line-height:1.6;margin:12px 0 0;}
    .insights-grid {gap:16px;}
    .record,.mechanism {padding-top:16px;}
    .section-head {flex-wrap:wrap;align-items:flex-start;gap:8px 12px;}
    .section-head h2 {font-size:clamp(26px,7vw,32px);}
    .source-tag {white-space:normal;padding-bottom:0;font-size:10px;}
    .description {font-size:12px;line-height:1.6;margin:10px 0 14px;}
    .event {padding:13px 0 13px 19px;gap:7px;}
    .event strong {font-size:16px;}
    .event time {font-size:12px;}
    .event-fallback {min-height:110px;padding:16px;}
    .source-note {font-size:12px;line-height:1.55;padding-top:13px;margin:17px 0 0;}
    .mechanism {margin-top:3px;}
    .mechanism h2 {font-size:26px;margin-bottom:12px;}
    .phone-study-toggle {
      display:flex;box-sizing:border-box;align-items:center;justify-content:space-between;
      gap:14px;min-height:52px;width:100%;padding:12px 14px;
      border:1px solid rgba(214,183,128,.45);border-radius:10px;
      background:rgba(214,183,128,.06);color:#f5ddad;
      text-align:left;font:600 13px/1.4 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      cursor:pointer;
    }
    .phone-study-toggle:focus-visible {outline:3px solid #f1d499;outline-offset:3px;}
    .study-content.phone-collapsed {display:none;}
    .mechanism-intro {margin:15px 0;font-size:12px;line-height:1.6;}
    .stages {margin:18px 0 8px;}
    .stage {padding-bottom:17px;}
    .existing-link {min-height:48px;margin-top:14px;font-size:13px;}
    .mechanism-note {font-size:12px;line-height:1.55;}
    .review-footer {margin:29px 0 0;padding-top:17px;line-height:1.5;}
    .review-footer a {display:inline-flex;align-items:center;min-height:44px;}
  }
  @media(prefers-reduced-motion:reduce){.existing-link{scroll-behavior:auto}}
</style>
