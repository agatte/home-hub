<script>
  import { lights } from '$lib/stores/lights.js'
  import { sonos } from '$lib/stores/sonos.js'
  import { automation } from '$lib/stores/automation.js'
  import { modeColor, modeLabel } from '$lib/theme.js'
  import { lightStateToCSS } from '$lib/utils/lightColor.js'

  // Order lights deterministically — primary fixtures L1..L4 first, anything
  // else after. Matches the apartment's documented spatial layout (L1 desk
  // lamp, L2 bedroom, L3+L4 kitchen pair) so the row reads left-to-right
  // like a glance from the desk toward the kitchen.
  $: lightList = Object.values($lights ?? {}).sort((a, b) => {
    const aId = parseInt(a.light_id, 10)
    const bId = parseInt(b.light_id, 10)
    if (!isNaN(aId) && !isNaN(bId)) return aId - bId
    return a.name.localeCompare(b.name)
  })

  $: modeLabelText = modeLabel($automation?.mode || 'idle')
  $: modeColorCss = modeColor($automation?.mode || 'idle')
  $: sourceText = formatSource($automation?.source)

  $: nowPlaying = (() => {
    const s = $sonos
    if (!s) return null
    const playing = s.state === 'PLAYING'
    const paused = s.state === 'PAUSED_PLAYBACK'
    if (!playing && !paused) return null
    if (!s.track && !s.artist) return null
    return {
      track: s.track || 'Unknown track',
      artist: s.artist || '',
      state: playing ? 'PLAYING' : 'PAUSED',
    }
  })()

  /** @param {string} source */
  function formatSource(source) {
    if (!source) return ''
    // Sources arrive as 'process', 'camera', 'fusion', 'manual', 'gameday:auto', 'api:192.168.86.30', etc.
    // Show the bit before the colon for the dashboard glance — full string is in the agent narrative.
    return source.split(':')[0]
  }
</script>

<section class="output-card">
  <header class="output-head">
    <span class="output-eyebrow">Feeding the apartment</span>
  </header>

  <div class="output-row">
    <span class="output-label">MODE</span>
    <div class="mode-line">
      <span class="mode-name" style="color: {modeColorCss}">{modeLabelText}</span>
      {#if sourceText}
        <span class="mode-source">via {sourceText}</span>
      {/if}
      {#if $automation?.manual_override}
        <span class="mode-override-pill">override</span>
      {/if}
    </div>
  </div>

  <div class="output-row">
    <span class="output-label">LIGHTS</span>
    {#if lightList.length}
      <div class="lights-row">
        {#each lightList as light (light.light_id)}
          <div class="light-cell" class:light-off={!light.on}>
            <div
              class="light-swatch"
              class:light-swatch-off={!light.on}
              class:light-unreachable={!light.reachable}
              style="background: {lightStateToCSS(light)}"
            ></div>
            <span class="light-name">{light.name}</span>
          </div>
        {/each}
      </div>
    {:else}
      <span class="output-empty">no lights reporting</span>
    {/if}
  </div>

  <div class="output-row">
    <span class="output-label">MUSIC</span>
    {#if nowPlaying}
      <div class="music-line">
        <span class="music-state" class:music-paused={nowPlaying.state === 'PAUSED'}>
          {nowPlaying.state === 'PLAYING' ? '▶' : '⏸'}
        </span>
        <span class="music-track">{nowPlaying.track}</span>
        {#if nowPlaying.artist}
          <span class="music-artist">{nowPlaying.artist}</span>
        {/if}
      </div>
    {:else}
      <span class="output-empty">silent</span>
    {/if}
  </div>
</section>

<style>
  .output-card {
    background: rgba(20, 20, 32, 0.55);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: var(--radius-md, 14px);
    padding: 22px 24px;
    backdrop-filter: blur(10px);
    display: flex;
    flex-direction: column;
    gap: 18px;
  }

  .output-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    padding-bottom: 10px;
  }

  .output-eyebrow {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 13px;
    letter-spacing: 3px;
    color: rgba(255, 255, 255, 0.55);
    text-transform: uppercase;
  }

  .output-row {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .output-label {
    font-size: 10px;
    letter-spacing: 1.6px;
    text-transform: uppercase;
    color: rgba(255, 255, 255, 0.35);
  }

  .output-empty {
    font-size: 13px;
    color: var(--text-muted, rgba(255, 255, 255, 0.4));
    font-style: italic;
  }

  /* Mode line */
  .mode-line {
    display: flex;
    align-items: baseline;
    gap: 12px;
    flex-wrap: wrap;
  }
  .mode-name {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 30px;
    letter-spacing: 2px;
    line-height: 1;
    text-transform: uppercase;
  }
  .mode-source {
    font-size: 12px;
    color: var(--text-muted, rgba(255, 255, 255, 0.45));
    text-transform: lowercase;
  }
  .mode-override-pill {
    font-size: 10px;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    padding: 2px 8px;
    border-radius: 999px;
    border: 1px solid rgba(255, 180, 80, 0.6);
    color: rgba(255, 180, 80, 0.85);
  }

  /* Lights row */
  .lights-row {
    display: flex;
    gap: 16px;
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .light-cell {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    min-width: 56px;
  }
  .light-swatch {
    width: 44px;
    height: 44px;
    border-radius: 50%;
    border: 1px solid rgba(255, 255, 255, 0.12);
    box-shadow:
      inset 0 1px 2px rgba(255, 255, 255, 0.18),
      0 0 14px rgba(0, 0, 0, 0.35);
    transition: background 600ms ease, opacity 300ms ease;
  }
  .light-swatch-off {
    opacity: 0.4;
    box-shadow: inset 0 1px 2px rgba(255, 255, 255, 0.05);
  }
  .light-unreachable {
    border-style: dashed;
    border-color: rgba(255, 100, 100, 0.5);
  }
  .light-name {
    font-size: 11px;
    color: var(--text-muted, rgba(255, 255, 255, 0.55));
    text-align: center;
    max-width: 80px;
  }
  .light-cell.light-off .light-name {
    color: rgba(255, 255, 255, 0.3);
  }

  /* Music line */
  .music-line {
    display: flex;
    align-items: baseline;
    gap: 10px;
    flex-wrap: wrap;
    font-size: 14px;
  }
  .music-state {
    color: rgba(140, 220, 140, 0.85);
    font-size: 12px;
  }
  .music-state.music-paused {
    color: rgba(255, 255, 255, 0.45);
  }
  .music-track {
    color: var(--text-primary, #fff);
    font-weight: 600;
  }
  .music-artist {
    color: var(--text-muted, rgba(255, 255, 255, 0.55));
    font-size: 13px;
  }

  @media (max-width: 700px) {
    .output-card {
      padding: 18px 18px;
    }
    .mode-name {
      font-size: 26px;
    }
    .lights-row {
      gap: 10px;
    }
    .light-swatch {
      width: 36px;
      height: 36px;
    }
  }
</style>
