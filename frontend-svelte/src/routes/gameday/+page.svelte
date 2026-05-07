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
  <header class="scoreboard">
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

  <section class="field-container">
    <!-- Phase B slice D: replace with <FootballField {game} lastPlay={game.last_play} /> -->
    <div class="field-placeholder">
      <p>Threlte FootballField goes here</p>
      <p class="field-hint">Possession: {game.possession.toUpperCase()}</p>
    </div>
  </section>

  <footer class="last-play">
    <span class="last-play-label">Last play:</span>
    <span class="last-play-text">{game.last_play.description}</span>
  </footer>
</main>

<style>
  .gameday-page {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
    padding: 1.5rem;
    min-height: 100vh;
    color: var(--text-primary, #f5f5f5);
  }

  .scoreboard {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    align-items: center;
    gap: 2rem;
    padding: 1.5rem 2rem;
    background: rgba(0, 44, 95, 0.18);
    border: 1px solid rgba(0, 44, 95, 0.4);
    border-radius: 16px;
    backdrop-filter: blur(12px);
  }

  .team {
    display: flex;
    align-items: baseline;
    gap: 1.25rem;
  }
  .team-home { justify-content: flex-start; }
  .team-away { justify-content: flex-end; }

  .team-name {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 2rem;
    letter-spacing: 0.08em;
  }
  .team-score {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 4rem;
    font-weight: 600;
    line-height: 1;
  }

  .game-clock {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.25rem;
    font-family: 'Source Sans 3', sans-serif;
    text-align: center;
  }
  .quarter { font-size: 0.85rem; opacity: 0.7; letter-spacing: 0.15em; }
  .clock { font-size: 1.75rem; font-weight: 600; font-variant-numeric: tabular-nums; }

  .field-container {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 50vh;
  }

  .field-placeholder {
    width: 100%;
    max-width: 900px;
    aspect-ratio: 2 / 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    background: linear-gradient(135deg, rgba(0, 80, 30, 0.25) 0%, rgba(0, 60, 20, 0.35) 100%);
    border: 2px dashed rgba(255, 255, 255, 0.18);
    border-radius: 12px;
    color: rgba(255, 255, 255, 0.6);
    font-family: 'Source Sans 3', sans-serif;
  }
  .field-hint { font-size: 0.85rem; opacity: 0.7; }

  .last-play {
    display: flex;
    gap: 0.75rem;
    align-items: baseline;
    padding: 1rem 1.25rem;
    background: rgba(255, 255, 255, 0.05);
    border-radius: 12px;
    font-family: 'Source Sans 3', sans-serif;
  }
  .last-play-label {
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    font-size: 0.75rem;
    opacity: 0.7;
  }
  .last-play-text { font-size: 1rem; }
</style>
