<script>
  import { onMount } from 'svelte'
  import { gameday, initGamedayFeed } from '$lib/stores/gameday.js'

  const demo = {
    opponent: 'RAVENS',
    score_colts: 24,
    score_opp: 17,
    quarter: 3,
    clock: '4:26',
    possession: 'colts',
    current_drive: { plays: 6, yards: 48, elapsed: '2:11' },
  }

  onMount(() => initGamedayFeed())

  $: live = $gameday.state
  $: view = live ?? demo
  $: isPreview = live === null
  $: opponent = (view?.opponent || 'TBD').toUpperCase()
  $: quarter = view?.quarter ?? 0
  $: quarterLabel = quarter > 0 ? `${ordinal(quarter)} QUARTER` : 'PREGAME'
  $: drive = live?.current_drive ?? (isPreview ? demo.current_drive : null)
  $: possession = live?.possession === 'colts' ? 'COLTS BALL' : live?.possession === 'opp' ? `${opponent} BALL` : 'POSSESSION --'

  function ordinal(value) {
    return value === 1 ? '1ST' : value === 2 ? '2ND' : value === 3 ? '3RD' : `${value}TH`
  }
</script>
<svelte:head>
  <title>Game Day - Sculptural Field</title>
  <meta name="robots" content="noindex" />
</svelte:head>

<main class="prototype-page" aria-label="Game Day sculptural field prototype">
  <img class="hero-render" src="/gameday/blender/sculptural-field-v38.webp" alt="Premium Colts sculptural field scoreboard" />

  <section class="score-overlay" aria-label={isPreview ? 'Synthetic preview game score' : 'Live game score'}>
    <div class="team home">
      <span>COLTS</span>
      <strong>{view.score_colts ?? 0}</strong>
    </div>
    <div class="clock">
      <span>{quarterLabel}</span>
      <strong>{view.clock || '--'}</strong>
      <small>{view.possession === 'colts' ? 'COLTS POSSESSION' : view.possession === 'opp' ? `${opponent} POSSESSION` : 'GAME DAY'}</small>
    </div>
    <div class="team away">
      <span>{opponent}</span>
      <strong>{view.score_opp ?? 0}</strong>
    </div>
  </section>

  <aside class="drive-overlay" aria-label="Current drive context">
    {#if drive}
      <span>CURRENT DRIVE</span>
      <strong>{drive.plays ?? '--'} PLAYS</strong>
      <strong>{drive.yards ?? '--'} YARDS</strong>
      <strong>{drive.elapsed ?? drive.time ?? '--'}</strong>
    {:else}
      <span>LIVE CONTEXT</span>
      <strong>{possession}</strong>
      <strong>DRIVE DATA</strong>
      <strong>PENDING</strong>
    {/if}
  </aside>

  {#if isPreview}
    <div class="preview-chip">DESIGN PREVIEW</div>
  {/if}
</main>

<style>
  :global(html), :global(body) { margin: 0; background: #020711; }
  .prototype-page {
    position: relative;
    width: 100vw;
    height: 100dvh;
    overflow: hidden;
    background: #020711;
    color: #f5f8fc;
    font-family: Inter, system-ui, sans-serif;
  }
  .hero-render {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .score-overlay {
    position: absolute;
    left: 28.2%;
    top: 68.2%;
    width: 43.8%;
    display: grid;
    grid-template-columns: 1fr .82fr 1fr;
    align-items: end;
    gap: 1.35vw;
    text-shadow: 0 2px 12px #000;
  }
  .team { display: grid; gap: 2px; }
  .team.home { justify-items: end; }
  .team.away { justify-items: start; }
  .team span, .clock span {
    color: #dfe7f0;
    font-size: 10px;
    font-weight: 650;
    letter-spacing: .13em;
  }
  .team strong {
    font-size: 46px;
    line-height: .86;
    font-weight: 560;
    font-variant-numeric: tabular-nums;
  }
  .clock {
    display: grid;
    justify-items: center;
    gap: 2px;
    padding-bottom: 1px;
  }
  .clock strong {
    font-size: 31px;
    line-height: .92;
    font-weight: 560;
    font-variant-numeric: tabular-nums;
  }
  .clock small {
    color: #e1e8f0;
    font-size: 9px;
    font-weight: 650;
    letter-spacing: .08em;
    white-space: nowrap;
  }
  .drive-overlay {
    position: absolute;
    right: 16.0%;
    top: 68.3%;
    display: grid;
    gap: 2px;
    min-width: 104px;
    text-shadow: 0 2px 12px #000;
  }
  .drive-overlay span {
    color: #89a0ba;
    font-size: 9px;
    font-weight: 750;
    letter-spacing: .18em;
    margin-bottom: 1px;
  }
  .drive-overlay strong {
    font-size: 12px;
    font-weight: 600;
    letter-spacing: .07em;
  }
  .preview-chip {
    position: absolute;
    right: 14px;
    bottom: 12px;
    color: rgba(190, 207, 227, .55);
    font-size: 8px;
    font-weight: 650;
    letter-spacing: .18em;
  }

  @media (max-width: 1100px) {
    .score-overlay { left: 28%; width: 44.2%; top: 68.4%; }
    .team strong { font-size: 38px; }
    .clock strong { font-size: 26px; }
    .team span, .clock span { font-size: 8px; }
    .clock small { font-size: 7px; }
    .drive-overlay { right: 10.2%; top: 68.4%; min-width: 88px; }
    .drive-overlay span { font-size: 7px; }
    .drive-overlay strong { font-size: 10px; }
  }
</style>
