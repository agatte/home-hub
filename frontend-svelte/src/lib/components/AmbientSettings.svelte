<script>
  import { ambient } from '$lib/stores/ambient.js'
  import { apiPost } from '$lib/api.js'
  import Slider from '$lib/components/Slider.svelte'

  const MODE_LABELS = {
    working: 'Working',
    gaming: 'Gaming',
    relax: 'Relax',
    cooking: 'Cooking',
    idle: 'Idle',
    social: 'Social',
  }

  /** @type {string | null} */
  let saving = null

  /** @param {Record<string, any>} body */
  async function patch(body) {
    saving = 'ambient'
    try {
      await apiPost('/api/ambient/config', body)
    } catch {}
    saving = null
  }

  async function toggleSonos() {
    await patch({ sonos_enabled: !$ambient.sonos_enabled })
  }

  /** @param {number} v */
  async function setPresentVolume(v) {
    await patch({ sonos_present_volume: v })
  }

  /** @param {number} v */
  async function setAwayVolume(v) {
    await patch({ sonos_away_volume: v })
  }

  /** @param {string} mode @param {number|null} v */
  async function setModeVolume(mode, v) {
    await patch({ sonos_mode_volume_overrides: { [mode]: v } })
  }

  /** @param {string} mode @param {string} filename */
  async function setModeSound(mode, filename) {
    await patch({
      mode_sounds: { [mode]: filename || null },
    })
  }

  /** @param {string} mode @param {boolean} on */
  async function setModeAutoPlay(mode, on) {
    await patch({ mode_auto_play: { [mode]: on } })
  }

  // Resolve effective Sonos volume for a mode (override or default).
  /** @param {string} mode */
  function effectiveVolume(mode) {
    const overrides = $ambient.sonos_mode_volume_overrides || {}
    if (mode in overrides) return overrides[mode]
    return $ambient.sonos_present_volume
  }

  /** @param {string} mode */
  function hasOverride(mode) {
    const overrides = $ambient.sonos_mode_volume_overrides || {}
    return mode in overrides
  }

  $: suppressed = $ambient.suppressed_modes || ['watching', 'gameday', 'sleeping']
  $: hasSounds = $ambient.available_sounds && $ambient.available_sounds.length > 0
  $: sonosStatusLabel = (() => {
    if (!$ambient.sonos_enabled) return 'Browser only'
    if ($ambient.sonos_ambient_active) return 'Now playing on Sonos'
    if ($ambient.playing) return 'Sonos eligible, idle'
    return 'Ready'
  })()
</script>

<section class="widget">
  <h2 class="widget-title">Ambient Sound</h2>
  <p class="widget-hint">
    Weather-reactive background audio. Sonos is the primary surface when enabled and the mode
    isn't a suppressed one ({suppressed.join(', ')}); per-tab browser audio is silenced while
    Sonos is playing. Weather classes (rain, thunderstorm, snow, wind) take priority over
    mode mappings.
  </p>

  {#if !hasSounds}
    <div class="settings-card">
      <div class="setting-hint">
        No ambient sound files installed. Add .mp3 / .wav files to
        <code>backend/static/ambient/</code> (committed defaults) or
        <code>data/ambient/</code> (long-form user files, gitignored) and restart.
      </div>
    </div>
  {:else}
    <div class="settings-card">
      <!-- Master Sonos toggle -->
      <div class="setting-row">
        <div class="setting-info">
          <span class="setting-label">Play on Sonos</span>
          <span class="setting-hint">
            {#if $ambient.sonos_ambient_active}
              {sonosStatusLabel} — {$ambient.sound_label || $ambient.sound}
            {:else}
              {sonosStatusLabel}
            {/if}
          </span>
        </div>
        <button
          class="toggle-btn"
          class:toggle-on={$ambient.sonos_enabled}
          on:click={toggleSonos}
          disabled={saving === 'ambient'}
        >
          {$ambient.sonos_enabled ? 'ON' : 'OFF'}
        </button>
      </div>

      <!-- Present volume -->
      <div class="setting-row">
        <div class="setting-info">
          <span class="setting-label">Default Sonos volume</span>
          <span class="setting-hint">Level when you're in the room. Used as the fallback when a mode has no override.</span>
        </div>
        <div class="setting-slider-wrap">
          <Slider
            value={$ambient.sonos_present_volume ?? 12}
            min={0}
            max={60}
            liveUpdate={false}
            onChange={setPresentVolume}
          />
        </div>
      </div>

      <!-- Away volume (follow-me ramp) -->
      <div class="setting-row">
        <div class="setting-info">
          <span class="setting-label">Away Sonos volume</span>
          <span class="setting-hint">Ramped up after 8s of camera-detected absence so you can hear it from the kitchen / bathroom.</span>
        </div>
        <div class="setting-slider-wrap">
          <Slider
            value={$ambient.sonos_away_volume ?? 28}
            min={0}
            max={60}
            liveUpdate={false}
            onChange={setAwayVolume}
          />
        </div>
      </div>
    </div>

    <h3 class="ambient-subheading">Per-mode</h3>
    <p class="widget-hint">
      Pick a sound + auto-play for each mode and (optionally) override the Sonos volume.
      Weather always wins when active; the mode sound fills in during clear weather.
      Suppressed modes ({suppressed.join(', ')}) are silent on both surfaces — not shown.
    </p>

    <div class="settings-card">
      {#each Object.entries(MODE_LABELS) as [mode, label] (mode)}
        <div class="ambient-mode-row">
          <div class="ambient-mode-head">
            <span class="ambient-mode-name">{label}</span>
            <label class="ambient-autoplay">
              <input
                type="checkbox"
                checked={$ambient.mode_auto_play?.[mode] || false}
                on:change={(e) => setModeAutoPlay(mode, /** @type {HTMLInputElement} */ (e.currentTarget).checked)}
                disabled={saving === 'ambient'}
              />
              <span>Auto</span>
            </label>
          </div>
          <div class="ambient-mode-body">
            <select
              class="ambient-mode-select"
              aria-label="{label} sound"
              value={$ambient.mode_sounds?.[mode] || ''}
              on:change={(e) => setModeSound(mode, /** @type {HTMLSelectElement} */ (e.currentTarget).value)}
              disabled={saving === 'ambient'}
            >
              <option value="">None</option>
              {#each $ambient.available_sounds as s (s.filename)}
                <option value={s.filename}>{s.label}</option>
              {/each}
            </select>

            <div class="ambient-mode-vol">
              <span class="ambient-mode-vol-label">
                Sonos {effectiveVolume(mode)}{hasOverride(mode) ? '' : ' (default)'}
              </span>
              <Slider
                value={effectiveVolume(mode)}
                min={0}
                max={60}
                liveUpdate={false}
                onChange={(v) => setModeVolume(mode, v)}
              />
              {#if hasOverride(mode)}
                <button
                  class="ambient-clear-btn"
                  on:click={() => setModeVolume(mode, null)}
                  disabled={saving === 'ambient'}
                  title="Use default Sonos volume"
                >reset</button>
              {/if}
            </div>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</section>

<style>
  .ambient-subheading {
    font-family: var(--font-display);
    font-size: 14px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-muted);
    margin: 18px 0 4px;
  }

  .ambient-mode-row {
    padding: 10px 0;
  }

  .ambient-mode-row + .ambient-mode-row {
    border-top: 1px solid var(--border);
  }

  .ambient-mode-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 6px;
  }

  .ambient-mode-name {
    font-family: var(--font-body);
    font-size: 14px;
    font-weight: 500;
    color: var(--text-primary);
  }

  .ambient-autoplay {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--text-muted);
    cursor: pointer;
    user-select: none;
  }

  .ambient-autoplay input {
    accent-color: var(--accent, #8c64c8);
    cursor: pointer;
  }

  .ambient-mode-body {
    display: grid;
    grid-template-columns: minmax(120px, 1fr) minmax(180px, 2fr);
    gap: 10px;
    align-items: center;
  }

  .ambient-mode-select {
    padding: 6px 8px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-primary);
    font-family: var(--font-body);
    font-size: 12px;
    outline: none;
  }

  .ambient-mode-select:focus {
    border-color: var(--accent, #8c64c8);
  }

  .ambient-mode-select option {
    background: #1a1a2e;
    color: #fff;
  }

  .ambient-mode-vol {
    display: grid;
    grid-template-columns: auto 1fr auto;
    gap: 8px;
    align-items: center;
  }

  .ambient-mode-vol-label {
    font-family: var(--font-body);
    font-size: 11px;
    color: var(--text-muted);
    white-space: nowrap;
  }

  .ambient-clear-btn {
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-muted);
    font-family: var(--font-body);
    font-size: 11px;
    padding: 3px 8px;
    cursor: pointer;
    transition: background 0.2s, color 0.2s;
  }

  .ambient-clear-btn:hover {
    background: rgba(255, 255, 255, 0.12);
    color: var(--text-primary);
  }

  code {
    background: rgba(255, 255, 255, 0.06);
    border-radius: 4px;
    padding: 1px 4px;
    font-size: 11px;
  }

  @media (max-width: 720px) {
    .ambient-mode-body {
      grid-template-columns: 1fr;
    }
  }
</style>
