<script>
  /**
   * FootballField — Threlte 3D top-down football field for the /gameday page.
   *
   * Pure prop-driven component. No store imports, no API calls, no coupling
   * to the backend. The parent page passes in a GameDayState dict and the
   * latest PlayEvent (both shapes per docs/GAMEDAY_SPEC.md §4 and the
   * dataclasses in backend/services/gameday_service.py).
   *
   * Renders:
   *   - low-poly green field (100yd × 53yd plane), striped for that
   *     mowed-grass broadcast look
   *   - white yard-line decals every 5 yards (thicker at midfield)
   *   - colored endzones (left = Colts theme primary, right = neutral)
   *   - team initial labels at each endzone (3D text via troika)
   *   - ball marker positioned by possession. The data model has no
   *     yardLine field yet, so we approximate: -25 yard line if Colts
   *     have ball, +25 if opponent does, midfield if null.
   *   - HTML floating scoreboard above the field. Easier to size and
   *     style than 3D text for a tabular score / quarter / clock.
   *
   * Defensive: if `game` is null or has unexpected shape, renders a faded
   * empty field with a placeholder scoreboard. Never throws.
   */
  import { Canvas } from '@threlte/core'
  import FieldScene from './footballfield/FieldScene.svelte'

  /** @type {{
   *    status?: string,
   *    opponent?: string|null,
   *    score_colts?: number,
   *    score_opp?: number,
   *    quarter?: number,
   *    clock?: string,
   *    possession?: 'colts'|'opp'|null,
   *    last_play?: object|null
   *  } | null}
   */
  export let game = null

  /** @type {{ primary: string, secondary: string }} */
  export let theme = { primary: '#002C5F', secondary: '#FFFFFF' }

  // Derive display values defensively. Missing or wrong-shaped fields fall
  // back to placeholders; we never throw on bad input.
  $: hasGame =
    game !== null &&
    game !== undefined &&
    typeof game === 'object' &&
    game.status !== 'no-game'
  $: opponent = (game && game.opponent) || 'TBD'
  $: opponentAbbr = (opponent || 'OPP').slice(0, 3).toUpperCase()
  $: scoreColts =
    game && Number.isFinite(game.score_colts) ? game.score_colts : 0
  $: scoreOpp =
    game && Number.isFinite(game.score_opp) ? game.score_opp : 0
  $: quarter = game && Number.isFinite(game.quarter) ? game.quarter : 1
  $: clock = game && typeof game.clock === 'string' ? game.clock : '--:--'
  $: possession = (game && game.possession) || null
  $: status = (game && game.status) || 'no-game'

  // Quarter label — "OT" for >=5, otherwise Q1-Q4.
  $: quarterLabel = quarter >= 5 ? 'OT' : `Q${quarter}`

  // Ball X target. Future improvement: take an explicit yardLine prop
  // and animate transitions per-play. For now, possession-based heuristic.
  $: targetBallX = possession === 'colts' ? -25 : possession === 'opp' ? 25 : 0

  const reduceMotion =
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
</script>

<div class="football-field">
  <!--
    HTML scoreboard overlay. Absolute-positioned above the canvas; simpler
    to style and size than 3D text, and inherits page typography cleanly.
  -->
  <div class="scoreboard" class:scoreboard--faded={!hasGame}>
    <div class="team team--colts" style="--accent: {theme.primary};">
      <span class="team-abbr">IND</span>
      <span class="team-score">{scoreColts}</span>
    </div>
    <div class="game-meta">
      <span class="clock">{quarterLabel} · {clock}</span>
      <span class="status">{status}</span>
    </div>
    <div class="team team--opp">
      <span class="team-score">{scoreOpp}</span>
      <span class="team-abbr">{opponentAbbr}</span>
    </div>
  </div>

  <Canvas>
    <FieldScene
      {theme}
      {hasGame}
      {opponentAbbr}
      {targetBallX}
      {reduceMotion}
    />
  </Canvas>
</div>

<style>
  .football-field {
    position: relative;
    width: 100%;
    height: 100%;
    min-height: 360px;
    display: block;
  }

  .football-field :global(canvas) {
    display: block;
    width: 100%;
    height: 100%;
  }

  .scoreboard {
    position: absolute;
    top: 1rem;
    left: 50%;
    transform: translateX(-50%);
    z-index: 2;
    display: flex;
    align-items: center;
    gap: 1.5rem;
    padding: 0.75rem 1.25rem;
    border-radius: 14px;
    background: rgba(8, 12, 22, 0.72);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.45);
    color: #f5f7fb;
    font-family: 'Bebas Neue', 'Source Sans 3', sans-serif;
    letter-spacing: 0.04em;
    pointer-events: none;
    user-select: none;
  }

  .scoreboard--faded {
    opacity: 0.55;
  }

  .team {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
  }

  .team-abbr {
    font-size: 1.25rem;
    color: var(--accent, #cfd6e4);
    text-shadow: 0 0 8px rgba(0, 0, 0, 0.4);
  }

  .team-score {
    font-size: 2.25rem;
    line-height: 1;
    font-weight: 700;
  }

  .game-meta {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.15rem;
    min-width: 6rem;
    padding: 0 0.25rem;
    border-left: 1px solid rgba(255, 255, 255, 0.12);
    border-right: 1px solid rgba(255, 255, 255, 0.12);
  }

  .clock {
    font-size: 1.05rem;
    color: #f5f7fb;
  }

  .status {
    font-size: 0.7rem;
    text-transform: uppercase;
    color: rgba(245, 247, 251, 0.55);
    font-family: 'Source Sans 3', sans-serif;
    letter-spacing: 0.12em;
  }

  @media (max-width: 540px) {
    .scoreboard {
      gap: 1rem;
      padding: 0.5rem 0.85rem;
    }
    .team-score {
      font-size: 1.6rem;
    }
    .team-abbr {
      font-size: 1rem;
    }
    .game-meta {
      min-width: 4.5rem;
    }
    .clock {
      font-size: 0.85rem;
    }
  }
</style>
