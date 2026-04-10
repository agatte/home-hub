<script>
  import { onMount } from 'svelte'
  import { connected, deviceStatus } from '$lib/stores/connection.js'
  import { apiGet, apiPut, apiPost } from '$lib/api.js'
  import Slider from '$lib/components/Slider.svelte'

  const MODE_LABELS = {
    gaming: 'Gaming',
    working: 'Working',
    watching: 'Watching',
    relax: 'Relax',
    movie: 'Movie',
    social: 'Social',
  }

  const RAMP_OPTIONS = [30, 60, 90, 120]

  /** @type {any} */
  export let data = undefined
  /** @type {any} */
  export let params = undefined
  data; params;

  /** @type {any} */
  let health = null
  /** @type {any} */
  let autoConfig = null
  /** @type {any} */
  let scheduleConfig = null
  /** @type {'weekday' | 'weekend'} */
  let scheduleDay = 'weekday'
  /** @type {any} */
  let modeBrightness = null
  /** @type {any} */
  let routineConfig = null
  /** @type {any} */
  let winddownConfig = null
  /** @type {string | null} */
  let saving = null

  $: currentSchedule = scheduleConfig?.[scheduleDay]

  onMount(async () => {
    try { health = await apiGet('/health') } catch {}
    try { autoConfig = await apiGet('/api/automation/config') } catch {}
    try { scheduleConfig = await apiGet('/api/automation/schedule') } catch {}
    try { modeBrightness = await apiGet('/api/automation/mode-brightness') } catch {}
    try {
      const data = await apiGet('/api/routines')
      const routines = data.routines || []
      const morning = routines.find((/** @type {any} */ r) => r.name === 'morning_routine')
      if (morning) {
        const [h, m] = morning.time.split(':').map(Number)
        routineConfig = {
          hour: h,
          minute: m,
          enabled: morning.enabled,
          volume: morning.volume ?? 40,
        }
      }
      const winddown = routines.find((/** @type {any} */ r) => r.name === 'winddown_routine')
      if (winddown) {
        const [wh, wm] = winddown.time.split(':').map(Number)
        winddownConfig = {
          hour: wh,
          minute: wm,
          enabled: winddown.enabled,
          volume: winddown.volume ?? 20,
          activate_candlelight: winddown.activate_candlelight ?? true,
          weekdays_only: winddown.weekdays_only ?? false,
        }
      } else {
        winddownConfig = {
          hour: 21, minute: 0, enabled: false,
          volume: 20, activate_candlelight: true, weekdays_only: false,
        }
      }
    } catch {}
  })

  /** @param {Record<string, any>} updates */
  async function saveAutoConfig(updates) {
    autoConfig = { ...autoConfig, ...updates }
    saving = 'auto'
    try { await apiPut('/api/automation/config', autoConfig) } catch {}
    saving = null
  }

  /** @param {'weekday' | 'weekend'} dayType @param {Record<string, any>} updates */
  async function saveScheduleConfig(dayType, updates) {
    scheduleConfig = {
      ...scheduleConfig,
      [dayType]: { ...scheduleConfig[dayType], ...updates },
    }
    saving = 'schedule'
    try { await apiPut('/api/automation/schedule', scheduleConfig) } catch {}
    saving = null
  }

  /** @param {Record<string, number>} updates */
  async function saveModeBrightness(updates) {
    modeBrightness = { ...modeBrightness, ...updates }
    saving = 'brightness'
    try { await apiPut('/api/automation/mode-brightness', modeBrightness) } catch {}
    saving = null
  }

  /** @param {Record<string, any>} updates */
  async function saveRoutineConfig(updates) {
    routineConfig = { ...routineConfig, ...updates }
    saving = 'routine'
    try { await apiPut('/api/routines/morning/config', routineConfig) } catch {}
    saving = null
  }

  /** @param {Record<string, any>} updates */
  async function saveWinddownConfig(updates) {
    winddownConfig = { ...winddownConfig, ...updates }
    saving = 'winddown'
    try { await apiPut('/api/routines/winddown/config', winddownConfig) } catch {}
    saving = null
  }

  async function testTTS() {
    saving = 'tts'
    try {
      await apiPost('/api/sonos/tts', {
        text: 'Home Hub is connected and working.',
        volume: 10,
      })
    } catch {}
    saving = null
  }

  async function testWinddown() {
    saving = 'winddown-test'
    try { await apiPost('/api/routines/winddown/test', {}) } catch {}
    saving = null
  }

  /** @param {Event} e @param {'weekday' | 'weekend'} day @param {string} key */
  function onTimeHourChange(e, day, key) {
    const target = /** @type {HTMLInputElement} */ (e.target)
    const h = parseInt(target.value.split(':')[0])
    saveScheduleConfig(day, { [key]: h })
  }

  /** @param {Event} e */
  function onMorningTimeChange(e) {
    const target = /** @type {HTMLInputElement} */ (e.target)
    const [h, m] = target.value.split(':').map(Number)
    saveRoutineConfig({ hour: h, minute: m })
  }

  /** @param {Event} e */
  function onWinddownTimeChange(e) {
    const target = /** @type {HTMLInputElement} */ (e.target)
    const [h, m] = target.value.split(':').map(Number)
    saveWinddownConfig({ hour: h, minute: m })
  }

  /** @param {number} n */
  const pad = (n) => String(n).padStart(2, '0')
</script>

<main class="settings-page">
  <div class="page-grid">
  <!-- Device Status -->
  <section class="widget">
    <h2 class="widget-title">Device Status</h2>
    <div class="settings-card">
      <div class="device-row">
        <span class="device-dot {$connected ? 'dot-green' : 'dot-red'}" />
        <span class="device-name">Server</span>
        <span class="device-detail">{$connected ? 'Connected' : 'Disconnected'}</span>
      </div>
      <div class="device-row">
        <span class="device-dot {$deviceStatus.hue ? 'dot-green' : 'dot-red'}" />
        <span class="device-name">Hue Bridge</span>
        <span class="device-detail">{$deviceStatus.hue ? 'Connected' : 'Offline'}</span>
      </div>
      <div class="device-row">
        <span class="device-dot {$deviceStatus.sonos ? 'dot-green' : 'dot-red'}" />
        <span class="device-name">Sonos</span>
        <span class="device-detail">{$deviceStatus.sonos ? 'Connected' : 'Offline'}</span>
      </div>
      {#if health}
        <div class="device-row">
          <span class="device-dot dot-blue" />
          <span class="device-name">WebSocket Clients</span>
          <span class="device-detail">{health.websocket_clients}</span>
        </div>
      {/if}
    </div>
  </section>

  <!-- Automation -->
  <section class="widget">
    <h2 class="widget-title">Automation</h2>
    {#if autoConfig}
      <div class="settings-card">
        <div class="setting-row">
          <div class="setting-info">
            <span class="setting-label">Automation Enabled</span>
            <span class="setting-hint">Auto-detect gaming, working, etc.</span>
          </div>
          <button
            class="toggle-btn"
            class:toggle-on={autoConfig.enabled}
            on:click={() => saveAutoConfig({ enabled: !autoConfig.enabled })}
          >
            {autoConfig.enabled ? 'ON' : 'OFF'}
          </button>
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <span class="setting-label">Override Timeout</span>
            <span class="setting-hint">Hours before manual mode auto-clears</span>
          </div>
          <div class="setting-stepper">
            <button
              class="stepper-btn"
              on:click={() => saveAutoConfig({ override_timeout_hours: Math.max(1, autoConfig.override_timeout_hours - 1) })}
            >-</button>
            <span class="stepper-value">{autoConfig.override_timeout_hours}h</span>
            <button
              class="stepper-btn"
              on:click={() => saveAutoConfig({ override_timeout_hours: Math.min(12, autoConfig.override_timeout_hours + 1) })}
            >+</button>
          </div>
        </div>
      </div>
    {/if}
  </section>

  <!-- Light Schedule -->
  <section class="widget">
    <h2 class="widget-title">Light Schedule</h2>
    {#if scheduleConfig && currentSchedule}
      <div class="settings-card">
        <div class="schedule-tab-row">
          <button
            class="schedule-tab"
            class:schedule-tab-active={scheduleDay === 'weekday'}
            on:click={() => (scheduleDay = 'weekday')}
          >Weekday</button>
          <button
            class="schedule-tab"
            class:schedule-tab-active={scheduleDay === 'weekend'}
            on:click={() => (scheduleDay = 'weekend')}
          >Weekend</button>
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <span class="setting-label">Wake-up</span>
            <span class="setting-hint">Lights turn on (dim warm)</span>
          </div>
          <input
            type="time"
            class="setting-time"
            value={`${pad(currentSchedule.wake_hour)}:00`}
            on:change={(e) => onTimeHourChange(e, scheduleDay, 'wake_hour')}
          />
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <span class="setting-label">Morning Ramp</span>
            <span class="setting-hint">Gradual brighten duration</span>
          </div>
          <div class="setting-stepper">
            <button
              class="stepper-btn"
              on:click={() => {
                const idx = RAMP_OPTIONS.indexOf(currentSchedule.ramp_duration_minutes)
                if (idx > 0) saveScheduleConfig(scheduleDay, { ramp_duration_minutes: RAMP_OPTIONS[idx - 1] })
              }}
            >-</button>
            <span class="stepper-value">{currentSchedule.ramp_duration_minutes}m</span>
            <button
              class="stepper-btn"
              on:click={() => {
                const idx = RAMP_OPTIONS.indexOf(currentSchedule.ramp_duration_minutes)
                if (idx < RAMP_OPTIONS.length - 1) saveScheduleConfig(scheduleDay, { ramp_duration_minutes: RAMP_OPTIONS[idx + 1] })
              }}
            >+</button>
          </div>
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <span class="setting-label">Evening</span>
            <span class="setting-hint">Warm evening lighting starts</span>
          </div>
          <input
            type="time"
            class="setting-time"
            value={`${pad(currentSchedule.evening_start_hour)}:00`}
            on:change={(e) => onTimeHourChange(e, scheduleDay, 'evening_start_hour')}
          />
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <span class="setting-label">Wind-down</span>
            <span class="setting-hint">Dim lighting starts</span>
          </div>
          <input
            type="time"
            class="setting-time"
            value={`${pad(currentSchedule.winddown_start_hour)}:00`}
            on:change={(e) => onTimeHourChange(e, scheduleDay, 'winddown_start_hour')}
          />
        </div>
      </div>
    {/if}
  </section>

  <!-- Mode Brightness -->
  <section class="widget">
    <h2 class="widget-title">Mode Brightness</h2>
    {#if modeBrightness}
      <div class="settings-card">
        {#each Object.entries(MODE_LABELS) as [mode, label] (mode)}
          <div class="setting-row">
            <div class="setting-info">
              <span class="setting-label">{label}</span>
              <span class="setting-hint">{Math.round((modeBrightness[mode] ?? 1.0) * 100)}%</span>
            </div>
            <div class="setting-slider-wrap">
              <Slider
                value={Math.round((modeBrightness[mode] ?? 1.0) * 100)}
                min={30}
                max={150}
                onChange={(v) => saveModeBrightness({ [mode]: v / 100 })}
              />
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </section>

  <!-- Morning Routine -->
  <section class="widget">
    <h2 class="widget-title">Morning Routine</h2>
    {#if routineConfig}
      <div class="settings-card">
        <div class="setting-row">
          <div class="setting-info">
            <span class="setting-label">Enabled</span>
            <span class="setting-hint">Weather + traffic TTS at scheduled time</span>
          </div>
          <button
            class="toggle-btn"
            class:toggle-on={routineConfig.enabled}
            on:click={() => saveRoutineConfig({ enabled: !routineConfig.enabled })}
          >
            {routineConfig.enabled ? 'ON' : 'OFF'}
          </button>
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <span class="setting-label">Time</span>
            <span class="setting-hint">Weekdays only (Mon-Fri)</span>
          </div>
          <input
            type="time"
            class="setting-time"
            value={`${pad(routineConfig.hour)}:${pad(routineConfig.minute)}`}
            on:change={onMorningTimeChange}
          />
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <span class="setting-label">Volume</span>
          </div>
          <div class="setting-slider-wrap">
            <Slider
              value={routineConfig.volume}
              min={10}
              max={100}
              onChange={(v) => saveRoutineConfig({ volume: v })}
            />
          </div>
        </div>
      </div>
    {/if}
  </section>

  <!-- Evening Wind-Down -->
  <section class="widget">
    <h2 class="widget-title">Evening Wind-Down</h2>
    {#if winddownConfig}
      <div class="settings-card">
        <div class="setting-row">
          <div class="setting-info">
            <span class="setting-label">Enabled</span>
            <span class="setting-hint">Dim lights, lower volume, candlelight</span>
          </div>
          <button
            class="toggle-btn"
            class:toggle-on={winddownConfig.enabled}
            on:click={() => saveWinddownConfig({ enabled: !winddownConfig.enabled })}
          >
            {winddownConfig.enabled ? 'ON' : 'OFF'}
          </button>
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <span class="setting-label">Time</span>
          </div>
          <input
            type="time"
            class="setting-time"
            value={`${pad(winddownConfig.hour)}:${pad(winddownConfig.minute)}`}
            on:change={onWinddownTimeChange}
          />
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <span class="setting-label">Volume</span>
            <span class="setting-hint">Sonos volume during wind-down</span>
          </div>
          <div class="setting-slider-wrap">
            <Slider
              value={winddownConfig.volume}
              min={5}
              max={50}
              onChange={(v) => saveWinddownConfig({ volume: v })}
            />
          </div>
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <span class="setting-label">Candlelight</span>
            <span class="setting-hint">Activate Hue candlelight effect</span>
          </div>
          <button
            class="toggle-btn"
            class:toggle-on={winddownConfig.activate_candlelight}
            on:click={() => saveWinddownConfig({ activate_candlelight: !winddownConfig.activate_candlelight })}
          >
            {winddownConfig.activate_candlelight ? 'ON' : 'OFF'}
          </button>
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <span class="setting-label">Weekdays Only</span>
          </div>
          <button
            class="toggle-btn"
            class:toggle-on={winddownConfig.weekdays_only}
            on:click={() => saveWinddownConfig({ weekdays_only: !winddownConfig.weekdays_only })}
          >
            {winddownConfig.weekdays_only ? 'ON' : 'OFF'}
          </button>
        </div>

        <div class="action-row">
          <button
            class="action-btn"
            on:click={testWinddown}
            disabled={saving === 'winddown-test'}
          >
            {saving === 'winddown-test' ? 'Running...' : 'Test Wind-Down'}
          </button>
        </div>
      </div>
    {/if}
  </section>

  <!-- Quick Actions -->
  <section class="widget">
    <h2 class="widget-title">Quick Actions</h2>
    <div class="settings-card">
      <div class="action-row">
        <button class="action-btn" on:click={testTTS} disabled={saving === 'tts'}>
          {saving === 'tts' ? 'Speaking...' : 'Test TTS'}
        </button>
        <span class="setting-hint">Play a test message on Sonos</span>
      </div>
    </div>
  </section>

  </div>

  {#if saving}
    <div class="settings-saving">Saving...</div>
  {/if}
</main>

<style>
  .page-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 20px;
  }

  @media (max-width: 900px) {
    .page-grid {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
