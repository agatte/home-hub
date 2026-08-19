<script>
  import { onMount } from 'svelte'
  import { Palette } from 'lucide-svelte'
  import { apiGet, apiPut, apiDelete } from '$lib/api.js'
  import SettingsSection from '$lib/components/settings/SettingsSection.svelte'
  import SettingGroup from '$lib/components/settings/SettingGroup.svelte'
  import ModeAccordion from '$lib/components/settings/ModeAccordion.svelte'
  import PeriodSliders from '$lib/components/settings/PeriodSliders.svelte'
  import ScenePickerPopover from '$lib/components/settings/ScenePickerPopover.svelte'
  import Slider from '$lib/components/Slider.svelte'

  /** @typedef {{key: string, label: string, icon: string, accent: string, hasBrightness: boolean, hasVolume: boolean, hasSceneOverride: boolean}} ModeDef */

  /** @type {ModeDef[]} */
  const MODES = [
    { key: 'gaming',   label: 'Gaming',    icon: '🎮', accent: 'rgba(74, 108, 247, 0.22)',  hasBrightness: true,  hasVolume: true, hasSceneOverride: true  },
    { key: 'working',  label: 'Working',   icon: '💻', accent: 'rgba(74, 108, 247, 0.18)',  hasBrightness: true,  hasVolume: true, hasSceneOverride: true  },
    { key: 'watching', label: 'Watching',  icon: '🎬', accent: 'rgba(190, 165, 235, 0.20)', hasBrightness: true,  hasVolume: true,  hasSceneOverride: true  },
    { key: 'relax',    label: 'Relax',     icon: '🛋️', accent: 'rgba(251, 191, 36, 0.18)',  hasBrightness: true,  hasVolume: true, hasSceneOverride: true  },
    { key: 'cooking',  label: 'Cooking',   icon: '🍳', accent: 'rgba(248, 113, 113, 0.18)', hasBrightness: true,  hasVolume: true, hasSceneOverride: true  },
    { key: 'social',   label: 'Social',    icon: '🎉', accent: 'rgba(244, 114, 182, 0.22)', hasBrightness: true,  hasVolume: true, hasSceneOverride: true  },
    { key: 'gameday',  label: 'Game Day',  icon: '🏈', accent: 'rgba(52, 211, 153, 0.18)',  hasBrightness: false, hasVolume: true, hasSceneOverride: false },
  ]

  const PERIODS = [
    { key: 'day',     label: 'Day' },
    { key: 'evening', label: 'Evening' },
    { key: 'night',   label: 'Night' },
  ]

  /** @type {Record<string, number> | null} */
  let modeBrightness = null
  /** @type {Record<string, {day: number, evening: number, night: number, fade_duration_s: number}> | null} */
  let modeVolume = null
  /** @type {any[]} */
  let modeSceneOverrides = []
  /** @type {any[]} */
  let allScenes = []
  /** @type {string | null} */
  let saving = null
  /** @type {string} */
  let expandedMode = 'gaming'

  onMount(async () => {
    try { modeBrightness = await apiGet('/api/automation/mode-brightness') } catch {}
    try { modeVolume = await apiGet('/api/automation/mode-volume') } catch {}
    try {
      const data = /** @type {any} */ (await apiGet('/api/automation/mode-scenes'))
      modeSceneOverrides = data.overrides || []
    } catch {}
    try {
      const data = /** @type {any} */ (await apiGet('/api/scenes'))
      allScenes = data.scenes || []
    } catch {}
  })

  /** @param {string} mode */
  function summaryFor(mode) {
    /** @type {string[]} */
    const parts = []
    if (modeBrightness && modeBrightness[mode] != null) {
      parts.push(`${Math.round(modeBrightness[mode] * 100)}% bri`)
    }
    if (modeVolume && modeVolume[mode]) {
      const v = modeVolume[mode]
      parts.push(`vol ${v.day}/${v.evening}/${v.night}`)
    }
    return parts.join(' · ')
  }

  /** @param {string} mode @param {number} pct */
  async function saveModeBrightness(mode, pct) {
    if (!modeBrightness) return
    modeBrightness = { ...modeBrightness, [mode]: pct / 100 }
    saving = 'brightness'
    try { await apiPut('/api/automation/mode-brightness', modeBrightness) } catch {}
    saving = null
  }

  /** @param {string} mode @param {string} key @param {number} value */
  async function saveModeVolume(mode, key, value) {
    if (!modeVolume) return
    modeVolume = { ...modeVolume, [mode]: { ...modeVolume[mode], [key]: value } }
    saving = 'volume'
    try { await apiPut('/api/automation/mode-volume', { [mode]: modeVolume[mode] }) } catch {}
    saving = null
  }


  /** @param {string} mode @param {string} period */
  function getOverride(mode, period) {
    return modeSceneOverrides.find(
      (/** @type {any} */ o) => o.mode === mode && o.time_period === period
    )
  }

  /** @param {string} mode @param {string} period @param {any} scene */
  async function setScene(mode, period, scene) {
    saving = 'scene'
    try {
      await apiPut(`/api/automation/mode-scenes/${mode}/${period}`, {
        scene_id: scene.id,
        scene_source: scene.source,
        scene_name: scene.display_name || scene.name,
      })
      const data = /** @type {any} */ (await apiGet('/api/automation/mode-scenes'))
      modeSceneOverrides = data.overrides || []
    } catch {}
    saving = null
  }

  /** @param {string} mode @param {string} period */
  async function clearScene(mode, period) {
    saving = 'scene'
    try {
      await apiDelete(`/api/automation/mode-scenes/${mode}/${period}`)
      const data = /** @type {any} */ (await apiGet('/api/automation/mode-scenes'))
      modeSceneOverrides = data.overrides || []
    } catch {}
    saving = null
  }

  /** @param {string} mode */
  function expand(mode) {
    expandedMode = expandedMode === mode ? '' : mode
  }
</script>

<SettingsSection
  title="Modes"
  description="Brightness, volume, and scene mapping — one card per mode. Tap to expand."
  icon={Palette}
>
  <div class="mode-stack">
    {#each MODES as mode (mode.key)}
      <ModeAccordion
        mode={mode.key}
        label={mode.label}
        icon={mode.icon}
        accent={mode.accent}
        summary={summaryFor(mode.key)}
        expanded={expandedMode === mode.key}
        on:click={() => expand(mode.key)}
      >
        {#if mode.hasBrightness && modeBrightness}
          <SettingGroup title="Brightness multiplier" hint="Range 30–150% of the per-light baseline. >100% boosts the curve.">
            <div class="brightness-row">
              <span class="brightness-value">{Math.round((modeBrightness[mode.key] ?? 1.0) * 100)}%</span>
              <Slider
                value={Math.round((modeBrightness[mode.key] ?? 1.0) * 100)}
                min={30}
                max={150}
                onChange={(v) => saveModeBrightness(mode.key, v)}
              />
            </div>
          </SettingGroup>
        {/if}

        {#if mode.hasVolume && modeVolume && modeVolume[mode.key]}
          <SettingGroup title="Sonos volume by period" hint="Smooth fade on mode change. Sleeping is forced to 0; DND suppresses fade.">
            <PeriodSliders
              periods={PERIODS}
              values={{
                day: modeVolume[mode.key].day,
                evening: modeVolume[mode.key].evening,
                night: modeVolume[mode.key].night,
              }}
              min={0}
              max={60}
              liveUpdate={false}
              onChange={(key, v) => saveModeVolume(mode.key, key, v)}
            />
            <div class="fade-row">
              <span class="fade-label">Fade duration</span>
              <input
                type="number"
                class="fade-input"
                min="1"
                max="30"
                value={modeVolume[mode.key].fade_duration_s}
                on:change={(e) => {
                  const v = Number(/** @type {HTMLInputElement} */ (e.currentTarget).value)
                  if (Number.isFinite(v)) saveModeVolume(mode.key, 'fade_duration_s', v)
                }}
                aria-label="{mode.label} fade duration seconds"
              />
              <span class="fade-unit">seconds</span>
            </div>
          </SettingGroup>
        {/if}


        {#if mode.hasSceneOverride}
          <SettingGroup title="Scene override by period" hint="Map a Hue scene to this mode at each time of day. Overrides default automation lighting.">
            <div class="scene-row">
              {#each PERIODS as period (period.key)}
                <div class="scene-col">
                  <span class="scene-col-label">{period.label}</span>
                  <ScenePickerPopover
                    scenes={allScenes}
                    selected={getOverride(mode.key, period.key) ? { id: 'override', source: '', name: getOverride(mode.key, period.key).scene_name } : null}
                    onPick={(s) => setScene(mode.key, period.key, s)}
                    onClear={() => clearScene(mode.key, period.key)}
                  />
                </div>
              {/each}
            </div>
          </SettingGroup>
        {/if}
      </ModeAccordion>
    {/each}
  </div>
</SettingsSection>

<style>
  .mode-stack {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .brightness-row {
    display: grid;
    grid-template-columns: 48px 1fr;
    gap: 12px;
    align-items: center;
  }

  .brightness-value {
    font-family: var(--font-body);
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
    font-variant-numeric: tabular-nums;
  }

  .fade-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 4px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
  }

  .fade-label {
    flex: 1;
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--text-muted);
  }

  .fade-input {
    width: 64px;
    padding: 6px 10px;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: var(--bg-secondary);
    color: var(--text-primary);
    font-family: var(--font-body);
    font-size: 13px;
    text-align: center;
    outline: none;
    color-scheme: dark;
  }

  .fade-input:focus {
    border-color: var(--accent);
  }

  .fade-input:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }

  .fade-unit {
    font-family: var(--font-body);
    font-size: 11px;
    color: var(--text-muted);
  }


  .scene-row {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
  }

  .scene-col {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
  }

  .scene-col-label {
    font-family: var(--font-body);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-muted);
  }

  @media (max-width: 540px) {
    .scene-row {
      grid-template-columns: 1fr;
    }
  }
</style>
