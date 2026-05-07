<script>
  import { onMount } from 'svelte'
  import { gameday, fetchGamedayInitial } from '$lib/stores/gameday.js'

  /** @type {any} */
  export let data = undefined
  /** @type {any} */
  export let params = undefined
  data; params;

  onMount(() => {
    // Best-effort REST priming. WS messages route in via init.js's central
    // dispatcher (wired post-merge by main session). Until then, only REST
    // data appears — fine because there's no live game in May 2026.
    fetchGamedayInitial()
  })

  // Reactive view-model. Pull from the store so the no-game vs in-game
  // branches stay declarative.
  $: state = $gameday.state
  $: lastPlay = $gameday.lastPlay
  $: schedule = $gameday.schedule
  $: scheduleLoaded = $gameday.scheduleLoaded
  $: hasGame = state !== null

  // No-game fallback — next scheduled game (or "no schedule yet").
  $: nextGame = schedule.length > 0 ? schedule[0] : null
  $: nextGameLabel = nextGame
    ? `Next: ${nextGame.opponent || 'TBD'} · ${formatKickoff(nextGame.kickoff_utc)}`
    : scheduleLoaded
      ? 'No game scheduled'
      : 'Loading schedule...'

  // In-game derived values. Guard with `state &&` so the markup template
  // can read them unconditionally without throwing.
  $: scoreColts = state?.score_colts ?? 0
  $: scoreOpp = state?.score_opp ?? 0
  $: opponent = (state?.opponent || 'TBD').toUpperCase()
  $: quarter = state?.quarter ?? 0
  $: clock = state?.clock || ''
  $: lastPlayDescription =
    lastPlay?.description ||
    state?.last_play?.description ||
    'Awaiting first play...'

  /**
   * Format an ISO kickoff timestamp into a short human-readable label.
   * Falls back to the raw string on parse failure.
   * @param {string | null | undefined} iso
   */
  function formatKickoff(iso) {
    if (!iso) return 'TBD'
    try {
      const dt = new Date(iso)
      if (Number.isNaN(dt.getTime())) return iso
      return dt.toLocaleDateString(undefined, {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
      })
    } catch (_) {
      return iso
    }
  }
</script>

<main class="gameday-page">
  <!-- Phase B slice D: replace .field-stub with <FootballField {game} lastPlay={game.last_play} /> -->
  <div class="field-stub" aria-hidden="true">
    <span class="field-stub-hint">Field placeholder · Slice D</span>
  </div>

  {#if hasGame}
    <header class="hud hud-scoreboard">
      <div class="team team-home">
        <span class="team-name">COLTS</span>
        <span class="team-score">{scoreColts}</span>
      </div>
      <div class="game-clock">
        <span class="quarter">Q{quarter}</span>
        <span class="clock">{clock}</span>
      </div>
      <div class="team team-away">
        <span class="team-score">{scoreOpp}</span>
        <span class="team-name">{opponent}</span>
      </div>
    </header>

    <footer class="hud hud-last-play">
      <span class="last-play-label">Last play</span>
      <span class="last-play-text">{lastPlayDescription}</span>
    </footer>
  {:else}
    <header class="hud hud-scoreboard hud-scoreboard-empty">
      <span class="next-game">{nextGameLabel}</span>
    </header>

    <footer class="hud hud-last-play">
      <span class="last-play-label">Schedule</span>
      <span class="last-play-text">
        Schedule loads from ESPN — typically May/June for the 2026 season.
      </span>
    </footer>
  {/if}
</main>

<style>
  .gameday-page {
    position: relative;
    width: 100%;
    min-height: 100dvh;
    color: var(--text-primary);
  }

  /* Field placeholder — full bleed behind the HUDs. Layered backgrounds:
     base grass → vertical yard lines every 10% → midfield 50-yard line →
     endzone tints via ::before/::after. Drop-in replacement for the
     eventual <FootballField /> Threlte component (Slice D). */
  .field-stub {
    position: absolute;
    inset: 0;
    overflow: hidden;
    background:
      /* midfield 50-yard line */
      linear-gradient(
        to right,
        transparent 0,
        transparent calc(50% - 1.5px),
        rgba(255, 255, 255, 0.32) calc(50% - 1.5px),
        rgba(255, 255, 255, 0.32) calc(50% + 1.5px),
        transparent calc(50% + 1.5px),
        transparent 100%
      ),
      /* yard lines every 10% of width */
      repeating-linear-gradient(
        to right,
        transparent 0,
        transparent calc(10% - 1px),
        rgba(255, 255, 255, 0.18) calc(10% - 1px),
        rgba(255, 255, 255, 0.18) 10%
      ),
      /* base grass */
      linear-gradient(180deg, #1a4a26 0%, #143820 100%);
  }

  .field-stub::before,
  .field-stub::after {
    content: '';
    position: absolute;
    top: 0;
    bottom: 0;
    width: 10%;
    pointer-events: none;
  }
  .field-stub::before {
    left: 0;
    background: rgba(0, 44, 95, 0.32);
    border-right: 2px solid rgba(255, 255, 255, 0.4);
  }
  .field-stub::after {
    right: 0;
    background: rgba(255, 255, 255, 0.06);
    border-left: 2px solid rgba(255, 255, 255, 0.4);
  }

  .field-stub-hint {
    position: absolute;
    bottom: 130px;
    left: 50%;
    transform: translateX(-50%);
    font-family: var(--font-body);
    font-size: 11px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: var(--text-muted);
    opacity: 0.7;
  }

  /* HUD shared surface — same glass as .widget so chrome reads cohesive. */
  .hud {
    position: absolute;
    left: 50%;
    transform: translateX(-50%);
    background: var(--bg-card);
    backdrop-filter: var(--glass-blur) var(--glass-saturate);
    -webkit-backdrop-filter: var(--glass-blur) var(--glass-saturate);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
  }

  /* Scoreboard HUD — top-center, clears ModeOverlay (~80px) + 8px gutter. */
  .hud-scoreboard {
    top: 88px;
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    align-items: center;
    gap: 2.5rem;
    padding: 18px 32px;
    background:
      linear-gradient(135deg, rgba(0, 44, 95, 0.28) 0%, transparent 60%),
      var(--bg-card);
  }

  /* No-game variant — single centered "Next: ..." line, same glass + border. */
  .hud-scoreboard-empty {
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 22px 36px;
  }
  .next-game {
    font-family: var(--font-display);
    font-size: 1.85rem;
    letter-spacing: 0.06em;
    color: var(--text-primary);
    text-align: center;
  }

  .team {
    display: flex;
    align-items: baseline;
    gap: 1.25rem;
  }
  .team-home {
    justify-content: flex-start;
    padding-left: 12px;
    border-left: 3px solid #002C5F;
  }
  .team-away {
    justify-content: flex-end;
    padding-right: 12px;
    border-right: 3px solid var(--border-hover);
  }

  .team-name {
    font-family: var(--font-display);
    font-size: 1.85rem;
    letter-spacing: 0.08em;
    color: var(--text-primary);
  }
  .team-score {
    font-family: var(--font-display);
    font-size: 4rem;
    font-weight: 600;
    line-height: 1;
    font-variant-numeric: tabular-nums;
    color: var(--text-primary);
  }

  .game-clock {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    font-family: var(--font-body);
    text-align: center;
  }
  .quarter {
    font-size: 11px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: var(--text-muted);
  }
  .clock {
    font-size: 1.65rem;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    color: var(--text-primary);
  }

  /* Last-play HUD — bottom-center, clears FloatingNav (44px @ bottom: 36px)
     + VitalStrip (22px) + 8px gutter = 110px total. */
  .hud-last-play {
    bottom: 110px;
    display: flex;
    gap: 14px;
    align-items: baseline;
    padding: 14px 22px;
    max-width: min(720px, calc(100vw - 48px));
  }
  .last-play-label {
    font-family: var(--font-body);
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 1px;
    font-size: 11px;
    color: var(--text-muted);
    flex-shrink: 0;
  }
  .last-play-text {
    font-family: var(--font-body);
    font-size: 14px;
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  @media (max-width: 768px) {
    .hud-scoreboard {
      top: 64px;
      gap: 1rem;
      padding: 14px 18px;
    }
    .team-name { font-size: 1.2rem; }
    .team-score { font-size: 2.6rem; }
    .clock { font-size: 1.3rem; }
    .next-game { font-size: 1.2rem; }

    .hud-last-play {
      bottom: 100px;
      padding: 12px 16px;
      max-width: calc(100vw - 32px);
    }
    .last-play-text { font-size: 13px; }

    .field-stub-hint {
      bottom: 120px;
      font-size: 10px;
    }
  }
</style>
