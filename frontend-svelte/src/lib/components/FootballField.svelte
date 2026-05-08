<script>
  /**
   * FootballField — Threlte 3D football field for the /gameday page.
   *
   * Pure prop-driven component. No store imports, no API calls, no coupling
   * to the backend. The parent page passes in a GameDayState dict; the
   * page owns the HUD scoreboard.
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
   *
   * Defensive: if `game` is null or has unexpected shape, renders a faded
   * empty field. Never throws.
   */
  import { Canvas } from '@threlte/core'
  import { NoToneMapping } from 'three'
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
  $: possession = (game && game.possession) || null

  // Ball X target. Future improvement: take an explicit yardLine prop
  // and animate transitions per-play. For now, possession-based heuristic.
  $: targetBallX = possession === 'colts' ? -25 : possession === 'opp' ? 25 : 0

  const reduceMotion =
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
</script>

<div class="football-field">
  <!--
    Phase 2 changes vs Threlte defaults:
    - autoRender={false} — PostFX.svelte's EffectComposer drives
      rendering instead of Threlte's default render task.
    - toneMapping={NoToneMapping} — postprocessing's ToneMappingEffect
      applies ACES Filmic in the post chain; setting NoToneMapping on
      the renderer prevents double-tone-mapping.
    - shadows={true} stays for the sun + tower PointLights' shadows.
    - antialiasing requested on the WebGL context for cleaner decals.
  -->
  <Canvas
    rendererParameters={{ antialias: true }}
    shadows={true}
    autoRender={false}
    toneMapping={NoToneMapping}
  >
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
    height: 100dvh;
    min-height: 0;
    display: block;
  }

  .football-field :global(canvas) {
    display: block;
    width: 100%;
    height: 100%;
  }
</style>
