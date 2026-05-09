<script>
  import { Cpu, Video, Mic, Clock, Sun, Cloud, Music, Lightbulb } from 'lucide-svelte'
  import { sectorBoard } from '$lib/stores/sectorBoard.js'
  import { modeColor, modeLabel } from '$lib/theme.js'
  import { lightStateToCSS } from '$lib/utils/lightColor.js'

  const ICON_MAP = { cpu: Cpu, video: Video, mic: Mic, clock: Clock, sun: Sun, cloud: Cloud, music: Music, lightbulb: Lightbulb }

  // Order for the 2-col input grid (lights split out as a footer row).
  const INPUT_IDS = ['process', 'camera', 'audio', 'rules', 'time', 'weather', 'sonos']

  const META = {
    process: { label: 'Process', icon: 'cpu' },
    camera:  { label: 'Camera',  icon: 'video' },
    audio:   { label: 'Audio',   icon: 'mic' },
    rules:   { label: 'Rules',   icon: 'clock' },
    time:    { label: 'Time',    icon: 'sun' },
    weather: { label: 'Weather', icon: 'cloud' },
    sonos:   { label: 'Sonos',   icon: 'music' },
  }

  $: fusedMode = $sectorBoard.mode.current
  $: confidencePct = Math.round(($sectorBoard.mode.confidence ?? 0) * 100)
  $: lights = $sectorBoard.sectors.lights?.lights || []
</script>

<section class="mobile-board">
  <header class="mode-card" style="--mode-color: {modeColor(fusedMode)};">
    <span class="mode-eyebrow">Current mode</span>
    <span class="mode-label">{modeLabel(fusedMode).toUpperCase()}</span>
    <span class="mode-conf">{confidencePct}% confidence</span>
    {#if $sectorBoard.mode.override}
      <span class="mode-pill mode-pill-override">Manual override</span>
    {/if}
    {#if $sectorBoard.mode.dnd}
      <span class="mode-pill mode-pill-dnd">Do not disturb</span>
    {/if}
  </header>

  <div class="input-grid">
    {#each INPUT_IDS as id}
      {@const data = $sectorBoard.sectors[id]}
      {@const meta = META[id]}
      {@const Icon = ICON_MAP[meta.icon]}
      <article
        class="input-card"
        class:stale={data?.stale}
        class:no-data={!data?.hasData}
        style="--card-color: {data?.hasData ? (data?.mode ? modeColor(data.mode) : modeColor(fusedMode)) : 'rgba(255,255,255,0.25)'};"
      >
        <header class="input-card-head">
          <span class="input-card-icon"><svelte:component this={Icon} size={16} /></span>
          <span class="input-card-label">{meta.label}</span>
          {#if data?.hasData && typeof data?.weight === 'number' && data.weight > 0}
            <span class="input-card-weight">{Math.round(data.weight * 100)}%</span>
          {/if}
        </header>
        {#if data?.factors?.length}
          <ul class="factor-list">
            {#each data.factors.slice(0, 3) as f (f.key)}
              <li>
                <span class="factor-display">{f.display}</span>
                {#if f.label && f.label.toLowerCase() !== f.display?.toLowerCase()}
                  <span class="factor-label">{f.label}</span>
                {/if}
              </li>
            {/each}
          </ul>
        {:else}
          <p class="factor-empty">no signal</p>
        {/if}
      </article>
    {/each}
  </div>

  <footer class="lights-row">
    <span class="lights-eyebrow">Lights</span>
    <div class="lights-strip">
      {#each lights as light (light.light_id)}
        <div class="light-cell" class:light-off={!light.on}>
          <div class="light-bulb" style="background: {lightStateToCSS(light)};"></div>
          <span class="light-name">{light.name}</span>
        </div>
      {/each}
    </div>
  </footer>
</section>

<style>
  .mobile-board {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 16px;
  }

  .mode-card {
    background: rgba(20, 20, 32, 0.55);
    border: 1px solid var(--mode-color);
    border-radius: 14px;
    padding: 18px 16px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    align-items: center;
    box-shadow: 0 0 24px var(--mode-color);
  }
  .mode-eyebrow {
    font-size: 10px;
    letter-spacing: 1.6px;
    text-transform: uppercase;
    color: var(--text-muted, rgba(255, 255, 255, 0.5));
  }
  .mode-label {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 32px;
    letter-spacing: 4px;
    color: var(--mode-color);
    line-height: 1.1;
  }
  .mode-conf {
    font-size: 12px;
    color: var(--text-muted, rgba(255, 255, 255, 0.55));
  }
  .mode-pill {
    margin-top: 6px;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1.2px;
  }
  .mode-pill-override {
    border: 1px solid rgba(255, 180, 80, 0.6);
    color: rgba(255, 200, 130, 0.95);
  }
  .mode-pill-dnd {
    border: 1px solid rgba(120, 160, 255, 0.6);
    color: rgba(170, 200, 255, 0.95);
  }

  .input-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }

  .input-card {
    background: rgba(20, 20, 32, 0.55);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 10px 12px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .input-card.stale,
  .input-card.no-data {
    opacity: 0.55;
  }

  .input-card-head {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--card-color);
  }
  .input-card-icon {
    display: flex;
    align-items: center;
  }
  .input-card-label {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 13px;
    letter-spacing: 1.6px;
    text-transform: uppercase;
    flex: 1;
  }
  .input-card-weight {
    font-size: 10px;
    color: var(--text-muted, rgba(255, 255, 255, 0.55));
  }

  .factor-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .factor-list li {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 6px;
  }
  .factor-display {
    font-size: 12px;
    color: var(--text-primary, #fff);
  }
  .factor-label {
    font-size: 9px;
    color: var(--text-muted, rgba(255, 255, 255, 0.4));
    text-transform: uppercase;
    letter-spacing: 0.8px;
  }
  .factor-empty {
    margin: 0;
    font-size: 11px;
    color: var(--text-muted, rgba(255, 255, 255, 0.35));
    font-style: italic;
  }

  .lights-row {
    background: rgba(20, 20, 32, 0.55);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 10px 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .lights-eyebrow {
    font-size: 10px;
    letter-spacing: 1.6px;
    text-transform: uppercase;
    color: var(--text-muted, rgba(255, 255, 255, 0.5));
  }
  .lights-strip {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
  }
  .light-cell {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    min-width: 44px;
  }
  .light-cell.light-off {
    opacity: 0.5;
  }
  .light-bulb {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    border: 1px solid rgba(255, 255, 255, 0.12);
    box-shadow: 0 0 10px rgba(0, 0, 0, 0.3);
  }
  .light-name {
    font-size: 9px;
    color: var(--text-muted, rgba(255, 255, 255, 0.55));
  }
</style>
