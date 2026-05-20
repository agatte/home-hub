<script>
  import { onMount } from 'svelte'
  import { Calendar } from 'lucide-svelte'
  import { apiGet, apiPut } from '$lib/api.js'
  import SettingsSection from '$lib/components/settings/SettingsSection.svelte'
  import SettingGroup from '$lib/components/settings/SettingGroup.svelte'
  import SettingRow from '$lib/components/settings/SettingRow.svelte'
  import SettingToggle from '$lib/components/settings/SettingToggle.svelte'
  import SettingButton from '$lib/components/settings/SettingButton.svelte'
  import Slider from '$lib/components/Slider.svelte'

  const RAMP_OPTIONS = [30, 60, 90, 120]

  /** @type {any} */
  let scheduleConfig = null
  /** @type {'weekday' | 'weekend'} */
  let scheduleDay = 'weekday'
  /** @type {any} */
  let routineConfig = null
  /** @type {string | null} */
  let saving = null

  $: currentSchedule = scheduleConfig?.[scheduleDay]

  onMount(async () => {
    try { scheduleConfig = await apiGet('/api/automation/schedule') } catch {}
    try {
      const data = /** @type {any} */ (await apiGet('/api/routines'))
      const morning = (data.routines || []).find((/** @type {any} */ r) => r.name === 'morning_routine')
      if (morning) {
        const [h, m] = morning.time.split(':').map(Number)
        routineConfig = { hour: h, minute: m, enabled: morning.enabled, volume: morning.volume ?? 40 }
      }
    } catch {}
  })

  /** @param {Record<string, any>} updates */
  async function saveScheduleConfig(updates) {
    if (!scheduleConfig) return
    scheduleConfig = {
      ...scheduleConfig,
      [scheduleDay]: { ...scheduleConfig[scheduleDay], ...updates },
    }
    saving = 'schedule'
    try { await apiPut('/api/automation/schedule', scheduleConfig) } catch {}
    saving = null
  }

  /** @param {Record<string, any>} updates */
  async function saveRoutineConfig(updates) {
    routineConfig = { ...routineConfig, ...updates }
    saving = 'routine'
    try { await apiPut('/api/routines/morning/config', routineConfig) } catch {}
    saving = null
  }

  /** @param {Event} e @param {string} key */
  function onTimeHourChange(e, key) {
    const target = /** @type {HTMLInputElement} */ (e.target)
    const h = parseInt(target.value.split(':')[0])
    saveScheduleConfig({ [key]: h })
  }

  /** @param {Event} e */
  function onMorningTimeChange(e) {
    const target = /** @type {HTMLInputElement} */ (e.target)
    const [h, m] = target.value.split(':').map(Number)
    saveRoutineConfig({ hour: h, minute: m })
  }

  /** @param {number} n */
  const pad = (n) => String(n).padStart(2, '0')

  function stepRamp(/** @type {number} */ dir) {
    if (!currentSchedule) return
    const idx = RAMP_OPTIONS.indexOf(currentSchedule.ramp_duration_minutes)
    const next = idx + dir
    if (next >= 0 && next < RAMP_OPTIONS.length) {
      saveScheduleConfig({ ramp_duration_minutes: RAMP_OPTIONS[next] })
    }
  }
</script>

<SettingsSection
  title="Schedule"
  description="When lighting cycles transition through the day, and what wakes you up. Indiana DST handled."
  icon={Calendar}
>
  {#if scheduleConfig && currentSchedule}
    <div class="day-tabs" role="tablist">
      <button
        role="tab"
        class="day-tab"
        class:active={scheduleDay === 'weekday'}
        aria-selected={scheduleDay === 'weekday'}
        on:click={() => (scheduleDay = 'weekday')}
      >Weekdays</button>
      <button
        role="tab"
        class="day-tab"
        class:active={scheduleDay === 'weekend'}
        aria-selected={scheduleDay === 'weekend'}
        on:click={() => (scheduleDay = 'weekend')}
      >Weekends</button>
    </div>

    <SettingGroup title="Light schedule">
      <SettingRow label="Wake-up" hint="Lights begin a warm dim ramp">
        <input
          type="time"
          class="time-input"
          value={`${pad(currentSchedule.wake_hour)}:00`}
          on:change={(e) => onTimeHourChange(e, 'wake_hour')}
          aria-label="{scheduleDay} wake-up time"
        />
      </SettingRow>

      <SettingRow label="Morning ramp" hint="How long to brighten from dim warm to full">
        <div class="stepper">
          <SettingButton variant="ghost" on:click={() => stepRamp(-1)}>−</SettingButton>
          <span class="stepper-val">{currentSchedule.ramp_duration_minutes}m</span>
          <SettingButton variant="ghost" on:click={() => stepRamp(1)}>+</SettingButton>
        </div>
      </SettingRow>

      <SettingRow label="Evening" hint="Warm evening lighting begins">
        <input
          type="time"
          class="time-input"
          value={`${pad(currentSchedule.evening_start_hour)}:00`}
          on:change={(e) => onTimeHourChange(e, 'evening_start_hour')}
          aria-label="{scheduleDay} evening start time"
        />
      </SettingRow>

      <SettingRow label="Wind-down" hint="Dim, low-stimulation lighting before sleep">
        <input
          type="time"
          class="time-input"
          value={`${pad(currentSchedule.winddown_start_hour)}:00`}
          on:change={(e) => onTimeHourChange(e, 'winddown_start_hour')}
          aria-label="{scheduleDay} wind-down start time"
        />
      </SettingRow>
    </SettingGroup>
  {/if}

  {#if routineConfig}
    <SettingGroup title="Morning routine" hint="Weather + traffic TTS on Sonos. Weekdays only (Mon–Fri).">
      <SettingRow label="Enabled" hint="Play the morning briefing at the scheduled time">
        <SettingToggle
          checked={!!routineConfig.enabled}
          onChange={(v) => saveRoutineConfig({ enabled: v })}
        />
      </SettingRow>
      <SettingRow label="Time">
        <input
          type="time"
          class="time-input"
          value={`${pad(routineConfig.hour)}:${pad(routineConfig.minute)}`}
          on:change={onMorningTimeChange}
          aria-label="Morning routine time"
        />
      </SettingRow>
      <SettingRow label="Volume" hint="{routineConfig.volume}%" stacked>
        <Slider
          value={routineConfig.volume}
          min={10}
          max={100}
          onChange={(v) => saveRoutineConfig({ volume: v })}
        />
      </SettingRow>
    </SettingGroup>
  {/if}
</SettingsSection>

<style>
  .day-tabs {
    display: inline-flex;
    padding: 4px;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: rgba(255, 255, 255, 0.03);
    align-self: flex-start;
  }

  .day-tab {
    padding: 6px 18px;
    border-radius: 999px;
    border: 0;
    background: transparent;
    color: var(--text-muted);
    font-family: var(--font-body);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.04em;
    cursor: pointer;
    transition: all 0.18s;
  }

  .day-tab:hover {
    color: var(--text-primary);
  }

  .day-tab.active {
    background: rgba(140, 100, 200, 0.22);
    color: var(--text-primary);
  }

  .time-input {
    padding: 6px 12px;
    border-radius: var(--radius-sm, 10px);
    border: 1px solid var(--border);
    background: var(--bg-secondary);
    color: var(--text-primary);
    font-family: var(--font-body);
    font-size: 13px;
    font-weight: 500;
    outline: none;
    color-scheme: dark;
    min-width: 110px;
  }

  .time-input:focus {
    border-color: var(--accent);
  }

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
    min-width: 44px;
    text-align: center;
    font-variant-numeric: tabular-nums;
  }
</style>
