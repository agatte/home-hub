<script>
  import { gameday } from '$lib/stores/gameday.js'
  import { buildPrototypePresentation, buildViewerSyncPendingPresentation } from '$lib/gameday/presentation.js'

  $: syncKnowledgePending = $gameday.viewerSyncLoaded !== true && $gameday.state !== null
  $: viewerClockActive = syncKnowledgePending || ($gameday.viewerSync?.enabled === true && $gameday.viewerSync?.presentation_active === true)
  $: viewerPresentation = viewerClockActive ? $gameday.viewerState : null
  $: live = viewerClockActive ? viewerPresentation : $gameday.state
  $: schedule = $gameday.schedule
  $: scheduleLoaded = $gameday.scheduleLoaded
  $: view = viewerClockActive && !viewerPresentation
    ? buildViewerSyncPendingPresentation($gameday.state)
    : buildPrototypePresentation(live, schedule, scheduleLoaded)
  $: opponent = view.opponent
  $: drive = view.drive
</script>
<svelte:head>
  <title>Game Day - Sculptural Field</title>
  <meta name="robots" content="noindex" />
</svelte:head>

<main class="prototype-page" aria-label="Game Day sculptural field prototype">
  <img
    class="hero-render"
    src="/gameday/futuristic-colts-clean-fascia.webp"
    alt="Futuristic Indianapolis Colts stadium scoreboard"
  />


  <section class="team home" aria-label="Colts score">
    <span>COLTS</span>
    <strong>{view.scoreColts}</strong>
  </section>

  <section class="clock" aria-label={view.isLive ? 'Live game clock' : 'Next game information'}>
    <span>{view.periodLabel}</span>
    <strong>{view.clock}</strong>
    <small>{view.subline}</small>
  </section>

  <section class="team away" aria-label={`${opponent} score`}>
    <span>{opponent}</span>
    <strong>{view.scoreOpp}</strong>
  </section>

  <aside class:placeholder={!drive} class="drive-overlay" aria-label={view.isLive ? 'Current game context' : 'Next game context'}>
    {#if drive}
      <span>CURRENT DRIVE</span>
      <strong>{drive.plays ?? '--'} PLAYS</strong>
      <strong>{drive.yards ?? '--'} YARDS</strong>
      <strong>{drive.elapsed ?? drive.time ?? '--'}</strong>
    {:else}
      <span>{view.sideLabel}</span>
      <strong>{view.sidePrimary}</strong>
      <strong>{view.sideSecondary}</strong>
    {/if}
  </aside>
</main>

<style>
  :global(html), :global(body) {
    margin: 0;
    background: #020711;
  }

  .prototype-page {
    position: relative;
    width: 100vw;
    height: 100dvh;
    overflow: hidden;
    background: #020711;
    color: #f7f9fc;
    font-family: "Arial Narrow", "Roboto Condensed", "Helvetica Neue", Arial, sans-serif;
  }
  .hero-render {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .team, .clock, .drive-overlay {
    position: absolute;
    z-index: 2;
    text-shadow: 0 2px 11px rgba(0, 0, 0, .92);
    top: 70.5%;
    transform: translateY(-50%);
  }
  .team {
    width: 8.5%;
    display: grid;
    justify-items: center;
    gap: 2px;
  }

  .team.home { left: 24.1%; }
  .team.away { left: 55.3%; }

  .team span, .clock span, .drive-overlay span {
    color: #d9e0e8;
    font-size: 11px;
    font-weight: 650;
    letter-spacing: .14em;
    line-height: 1;
  }

  .team strong {
    font-size: 46px;
    line-height: .9;
    font-weight: 600;
    font-stretch: condensed;
    font-variant-numeric: tabular-nums;
  }

  .clock {
    left: 40.1%;
    width: 10.6%;
    display: grid;
    justify-items: center;
    gap: 2px;
  }
  .clock strong {
    font-size: 38px;
    line-height: .94;
    font-weight: 600;
    font-stretch: condensed;
    font-variant-numeric: tabular-nums;
  }

  .clock small {
    color: #e5eaf0;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: .11em;
    line-height: 1;
    white-space: nowrap;
  }

  .drive-overlay {
    left: 70.8%;
    width: 12.3%;
    display: grid;
    gap: 3px;
    justify-items: start;
  }

  .drive-overlay.placeholder {
    justify-items: center;
    text-align: center;
  }

  .drive-overlay.placeholder strong {
    width: 100%;
  }

  .drive-overlay span {
    color: #d4dde7;
    font-size: 13px;
    font-weight: 700;
    margin-bottom: 2px;
  }

  .drive-overlay strong {
    color: #f1f5f9;
    font-size: 16px;
    line-height: 1.08;
    font-weight: 600;
    letter-spacing: .08em;
  }

  @media (max-width: 1100px) {
    .team span, .clock span, .drive-overlay span { font-size: 7px; }
    .team strong { font-size: 36px; }
    .clock strong { font-size: 28px; }
    .clock small { font-size: 6px; }
    .drive-overlay strong { font-size: 8px; }
  }
</style>
