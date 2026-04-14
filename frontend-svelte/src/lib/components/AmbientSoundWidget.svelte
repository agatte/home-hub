<script>
  import { ambient } from '$lib/stores/ambient.js'
  import { apiPost } from '$lib/api.js'

  let volumeTimeout

  async function togglePlay() {
    if ($ambient.playing) {
      await apiPost('/api/ambient/pause')
    } else if ($ambient.sound) {
      await apiPost('/api/ambient/resume')
    }
  }

  async function selectSound(filename) {
    if (!filename) {
      await apiPost('/api/ambient/stop')
    } else {
      await apiPost('/api/ambient/play', { filename })
    }
  }

  function onVolumeInput(e) {
    const vol = parseInt(e.target.value, 10) / 100
    // Optimistic local update for smooth slider feel
    ambient.update(s => ({ ...s, volume: vol }))
    // Debounce the API call
    clearTimeout(volumeTimeout)
    volumeTimeout = setTimeout(() => {
      apiPost('/api/ambient/volume', { volume: vol })
    }, 150)
  }

  async function toggleWeather() {
    await apiPost('/api/ambient/config', {
      weather_reactive: !$ambient.weather_reactive,
    })
  }

  $: volumePercent = Math.round(($ambient.volume || 0) * 100)
  $: hasSounds = $ambient.available_sounds && $ambient.available_sounds.length > 0
</script>

{#if hasSounds}
  <div class="ambient-content">
    <div class="ambient-main">
      <button class="ambient-play-btn" on:click={togglePlay} title={$ambient.playing ? 'Pause' : 'Play'}>
        <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          {#if $ambient.playing}
            <rect x="6" y="4" width="4" height="16" /><rect x="14" y="4" width="4" height="16" />
          {:else}
            <polygon points="5 3 19 12 5 21 5 3" />
          {/if}
        </svg>
      </button>

      <div class="ambient-info">
        <div class="ambient-sound-name">
          {$ambient.sound_label || 'Off'}
        </div>
        {#if $ambient.weather_override}
          <div class="ambient-source">
            <svg viewBox="0 0 24 24" width="10" height="10" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10Z" />
              <path d="M8 22v-2m4 2v-2m4 2v-2" />
            </svg>
            weather
          </div>
        {:else if $ambient.source === 'mode' && $ambient.playing}
          <div class="ambient-source">auto</div>
        {/if}
      </div>
    </div>

    <div class="ambient-controls">
      <select class="ambient-select" value={$ambient.sound || ''} on:change={(e) => selectSound(e.target.value)}>
        <option value="">None</option>
        {#each $ambient.available_sounds as s}
          <option value={s.filename}>{s.label}</option>
        {/each}
      </select>

      <div class="ambient-volume">
        <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          {#if volumePercent === 0}
            <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
            <line x1="23" y1="9" x2="17" y2="15" /><line x1="17" y1="9" x2="23" y2="15" />
          {:else}
            <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
            <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
          {/if}
        </svg>
        <input type="range" min="0" max="100" value={volumePercent} on:input={onVolumeInput} class="ambient-slider" />
        <span class="ambient-vol-label">{volumePercent}</span>
      </div>
    </div>

    <button class="ambient-weather-toggle" class:active={$ambient.weather_reactive} on:click={toggleWeather}>
      <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10Z" />
      </svg>
      Weather sync {$ambient.weather_reactive ? 'on' : 'off'}
    </button>
  </div>
{:else}
  <div class="ambient-empty">No sounds available</div>
{/if}

<style>
  .ambient-content {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .ambient-main {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .ambient-play-btn {
    background: none;
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 50%;
    width: 40px;
    height: 40px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-primary);
    cursor: pointer;
    transition: background 0.2s, border-color 0.2s;
    flex-shrink: 0;
  }

  .ambient-play-btn:hover {
    background: rgba(255, 255, 255, 0.08);
    border-color: rgba(255, 255, 255, 0.25);
  }

  .ambient-info {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .ambient-sound-name {
    font-family: var(--font-display);
    font-size: 22px;
    font-weight: 400;
    color: var(--text-primary);
    letter-spacing: 0.02em;
    line-height: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .ambient-source {
    display: flex;
    align-items: center;
    gap: 4px;
    font-family: var(--font-body);
    font-size: 10px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .ambient-controls {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .ambient-select {
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 6px;
    color: var(--text-primary);
    font-family: var(--font-body);
    font-size: 12px;
    padding: 6px 8px;
    cursor: pointer;
    outline: none;
    transition: border-color 0.2s;
  }

  .ambient-select:hover,
  .ambient-select:focus {
    border-color: rgba(255, 255, 255, 0.25);
  }

  .ambient-select option {
    background: #1a1a2e;
    color: #fff;
  }

  .ambient-volume {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--text-muted);
  }

  .ambient-slider {
    flex: 1;
    height: 4px;
    -webkit-appearance: none;
    appearance: none;
    background: rgba(255, 255, 255, 0.12);
    border-radius: 2px;
    outline: none;
    cursor: pointer;
  }

  .ambient-slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: var(--text-primary);
    cursor: pointer;
  }

  .ambient-slider::-moz-range-thumb {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: var(--text-primary);
    cursor: pointer;
    border: none;
  }

  .ambient-vol-label {
    font-family: var(--font-body);
    font-size: 11px;
    color: var(--text-muted);
    min-width: 20px;
    text-align: right;
  }

  .ambient-weather-toggle {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: none;
    border: none;
    font-family: var(--font-body);
    font-size: 11px;
    color: var(--text-muted);
    cursor: pointer;
    padding: 0;
    transition: color 0.2s;
  }

  .ambient-weather-toggle:hover {
    color: var(--text-secondary);
  }

  .ambient-weather-toggle.active {
    color: var(--text-secondary);
  }

  .ambient-empty {
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--text-muted);
    padding: 8px 0;
  }
</style>
