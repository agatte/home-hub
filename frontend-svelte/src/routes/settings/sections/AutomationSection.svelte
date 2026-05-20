<script>
  import { onMount } from 'svelte'
  import { Sliders, Camera, Brain } from 'lucide-svelte'
  import { camera as cameraStore } from '$lib/stores/camera.js'
  import { apiGet, apiPut, apiPost } from '$lib/api.js'
  import SettingsSection from '$lib/components/settings/SettingsSection.svelte'
  import SettingGroup from '$lib/components/settings/SettingGroup.svelte'
  import SettingRow from '$lib/components/settings/SettingRow.svelte'
  import SettingToggle from '$lib/components/settings/SettingToggle.svelte'
  import SettingButton from '$lib/components/settings/SettingButton.svelte'

  /** @type {any} */
  let autoConfig = null
  /** @type {{personality_enabled: boolean, desktop_emotion_enabled: boolean, desktop_presence_enabled: boolean} | null} */
  let personality = null
  /** @type {any} */
  let calibrateResult = null
  /** @type {string | null} */
  let saving = null

  $: desktopCameraOn = !!(
    personality?.personality_enabled &&
    (personality?.desktop_emotion_enabled || personality?.desktop_presence_enabled)
  )

  onMount(async () => {
    try { autoConfig = await apiGet('/api/automation/config') } catch {}
    try { personality = await apiGet('/api/personality/settings') } catch {}
  })

  /** @param {Record<string, any>} updates */
  async function saveAutoConfig(updates) {
    autoConfig = { ...autoConfig, ...updates }
    saving = 'auto'
    try { await apiPut('/api/automation/config', autoConfig) } catch {}
    saving = null
  }

  async function toggleCamera() {
    saving = 'camera'
    try {
      const enabled = !$cameraStore?.enabled
      await apiPost('/api/camera/enable', { enabled })
      $cameraStore = await apiGet('/api/camera/status')
    } catch {}
    saving = null
  }

  async function toggleDesktopCamera() {
    saving = 'desktop-camera'
    const target = !desktopCameraOn
    try {
      const payload = target
        ? { personality_enabled: true, desktop_emotion_enabled: true, desktop_presence_enabled: true }
        : { desktop_emotion_enabled: false, desktop_presence_enabled: false }
      personality = await apiPost('/api/personality/settings', payload)
    } catch {}
    saving = null
  }

  async function calibrateLux() {
    saving = 'calibrate'
    calibrateResult = null
    try {
      calibrateResult = await apiPost('/api/camera/calibrate', {})
      $cameraStore = await apiGet('/api/camera/status')
    } catch (err) {
      calibrateResult = { status: 'error', detail: err instanceof Error ? err.message : 'failed' }
    }
    saving = null
  }

  /** @param {number} n */
  function stepHours(n) {
    if (!autoConfig) return
    const next = Math.min(12, Math.max(1, autoConfig.override_timeout_hours + n))
    saveAutoConfig({ override_timeout_hours: next })
  }
</script>

<SettingsSection
  title="Automation"
  description="Master controls for autonomous behavior — what's allowed to drive the apartment without you."
  icon={Sliders}
>
  {#if autoConfig}
    <SettingGroup title="Engine">
      <SettingRow label="Autonomous mode detection" hint="Auto-flip between gaming / working / watching / relax based on process + camera + audio signals">
        <SettingToggle
          checked={autoConfig.enabled}
          saving={saving === 'auto' ? '…' : undefined}
          onChange={(v) => saveAutoConfig({ enabled: v })}
        />
      </SettingRow>
      <SettingRow label="Manual override timeout" hint="How long a manual mode choice sticks before auto-detection resumes">
        <div class="stepper">
          <SettingButton variant="ghost" on:click={() => stepHours(-1)}>−</SettingButton>
          <span class="stepper-val">{autoConfig.override_timeout_hours}h</span>
          <SettingButton variant="ghost" on:click={() => stepHours(1)}>+</SettingButton>
        </div>
      </SettingRow>
    </SettingGroup>
  {/if}

  <SettingGroup title="Cameras" hint="PresenceFusion merges both webcams into one zone + posture + lux read.">
    <SettingRow
      label="Latitude camera"
      hint="Kiosk webcam — presence, zone (desk / bed), posture, and ambient lux. Off by default."
    >
      <SettingToggle
        checked={!!$cameraStore?.enabled}
        saving={saving === 'camera' ? '…' : undefined}
        onChange={toggleCamera}
      />
    </SettingRow>

    {#if $cameraStore?.enabled}
      {#if $cameraStore.presence?.sources}
        <SettingRow label="Presence sources" hint="PresenceFusion lane freshness">
          <div class="source-list">
            {#each Object.entries($cameraStore.presence.sources) as [name, info]}
              <span class="source-chip" class:stale={!info.fresh}>
                {name} · {info.age_s?.toFixed(0) ?? '?'}s
              </span>
            {/each}
          </div>
        </SettingRow>
      {/if}

      <SettingRow label="Detection" hint="Most recent vision result">
        <span class="value-chip" class:ok={$cameraStore.last_detection === 'present'}>
          {$cameraStore.last_detection === 'present' ? 'Present' : $cameraStore.last_detection === 'absent' ? 'Absent' : 'Unknown'}
          {#if ($cameraStore.confidence ?? 0) > 0}
            <span class="value-sub">{(($cameraStore.confidence ?? 0) * 100).toFixed(0)}%</span>
          {/if}
        </span>
      </SettingRow>

      <SettingRow
        label="Ambient lux"
        hint={(() => {
          if ($cameraStore.calibrated && $cameraStore.baseline_lux != null) {
            return `lux ${($cameraStore.ema_lux ?? $cameraStore.ambient_lux ?? 0).toFixed(0)} / baseline ${$cameraStore.baseline_lux.toFixed(0)} → ×${($cameraStore.current_multiplier ?? 1).toFixed(2)}`
          }
          if ($cameraStore.calibrated) return 'Calibrated (pre-baseline) — recalibrate to anchor curve'
          return 'Uncalibrated — auto-exposure defeats the signal'
        })()}
      >
        <span class="value-chip mono">
          {$cameraStore.ema_lux?.toFixed(0) ?? $cameraStore.ambient_lux?.toFixed(0) ?? '--'} / 255
        </span>
      </SettingRow>

      <SettingRow
        label="Calibrate ambient light"
        hint={(() => {
          if (calibrateResult?.status === 'ok') {
            return `Calibrated: exposure ${calibrateResult.exposure_value?.toFixed(2)}, lux ~${calibrateResult.measured_lux?.toFixed(0)}`
          }
          if (calibrateResult?.status === 'error') return `Failed: ${calibrateResult.detail}`
          return 'Run once under typical lighting. Calibrate at comfortable bright, not a "feels dim" moment.'
        })()}
      >
        <SettingButton
          variant="accent"
          loading={saving === 'calibrate'}
          disabled={!!$cameraStore.paused}
          on:click={calibrateLux}
        >
          {saving === 'calibrate' ? 'Sampling…' : 'Calibrate'}
        </SettingButton>
      </SettingRow>

      {#if $cameraStore.paused}
        <p class="muted-hint">Camera paused during sleeping mode.</p>
      {/if}
    {/if}

    <SettingRow
      label="Desktop camera"
      hint="Emotion + presence from the desktop webcam. Releases the handle when off so Meet/Zoom can use it. ~30s for changes to apply."
    >
      <SettingToggle
        checked={desktopCameraOn}
        saving={saving === 'desktop-camera' ? '…' : undefined}
        disabled={personality === null}
        onChange={toggleDesktopCamera}
      />
    </SettingRow>
  </SettingGroup>

  {#if personality !== null}
    <SettingGroup title="Personality layer" hint="AI mood + vibe inference. Phase A: shadow-log only — no actuation.">
      <SettingRow label="Personality enabled" hint="Master switch for mood inference + future mood-ring lamp">
        <SettingToggle
          checked={!!personality.personality_enabled}
          saving={saving === 'desktop-camera' ? '…' : undefined}
          onChange={async (v) => {
            saving = 'personality'
            try {
              personality = await apiPost('/api/personality/settings', { personality_enabled: v })
            } catch {}
            saving = null
          }}
        />
      </SettingRow>
    </SettingGroup>
  {/if}
</SettingsSection>

<style>
  .stepper {
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }

  .stepper-val {
    font-family: var(--font-body);
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
    min-width: 38px;
    text-align: center;
    font-variant-numeric: tabular-nums;
  }

  .source-list {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    justify-content: flex-end;
  }

  .source-chip {
    display: inline-flex;
    padding: 3px 8px;
    border-radius: 999px;
    background: rgba(52, 211, 153, 0.14);
    border: 1px solid rgba(52, 211, 153, 0.32);
    color: var(--success);
    font-family: var(--font-body);
    font-size: 11px;
    font-weight: 500;
  }

  .source-chip.stale {
    background: rgba(251, 191, 36, 0.12);
    border-color: rgba(251, 191, 36, 0.36);
    color: rgb(251, 191, 36);
  }

  .value-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--border);
    color: var(--text-primary);
    font-family: var(--font-body);
    font-size: 12px;
    font-weight: 600;
  }

  .value-chip.ok {
    background: rgba(52, 211, 153, 0.12);
    border-color: rgba(52, 211, 153, 0.30);
    color: var(--success);
  }

  .value-chip.mono {
    font-family: ui-monospace, Menlo, Consolas, monospace;
  }

  .value-sub {
    color: var(--text-muted);
    font-weight: 500;
  }

  .muted-hint {
    margin: 0 4px;
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--text-muted);
  }
</style>
