<script>
  /** @type {any} */
  export let data = undefined
  /** @type {any} */
  export let params = undefined
  data; params;

  const game = {
    status: 'in-progress',
    opponent: 'Texans',
    score_colts: 21,
    score_opp: 14,
    quarter: 3,
    clock: '4:32',
    possession: 'colts',
    last_play: {
      description: 'Jonathan Taylor 5 yard run for a TOUCHDOWN',
      play_type: 'touchdown'
    }
  }
</script>

<main class="gameday-page">
  <!-- Phase B slice D: replace .field-stub with <FootballField {game} lastPlay={game.last_play} /> -->
  <div class="field-stub" aria-hidden="true">
    <span class="field-stub-hint">Field placeholder · Slice D</span>
  </div>

  <header class="hud hud-scoreboard">
    <div class="team team-home">
      <span class="team-name">COLTS</span>
      <span class="team-score">{game.score_colts}</span>
    </div>
    <div class="game-clock">
      <span class="quarter">Q{game.quarter}</span>
      <span class="clock">{game.clock}</span>
    </div>
    <div class="team team-away">
      <span class="team-score">{game.score_opp}</span>
      <span class="team-name">{game.opponent.toUpperCase()}</span>
    </div>
  </header>

  <footer class="hud hud-last-play">
    <span class="last-play-label">Last play</span>
    <span class="last-play-text">{game.last_play.description}</span>
  </footer>
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
