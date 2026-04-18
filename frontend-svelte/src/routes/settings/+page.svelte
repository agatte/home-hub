<script>
  import { onMount } from 'svelte'
  import { connected, deviceStatus } from '$lib/stores/connection.js'
  import { camera as cameraStore } from '$lib/stores/camera.js'
  import { apiGet, apiPut, apiPost, apiDelete } from '$lib/api.js'
  import Slider from '$lib/components/Slider.svelte'

  const MODE_LABELS = {
    gaming: 'Gaming',
    working: 'Working',
    watching: 'Watching',
    relax: 'Relax',
    cooking: 'Cooking',
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

  // Camera presence — driven by $cameraStore (real-time via WebSocket)

  // Mode → scene overrides
  /** @type {any[]} */
  let modeSceneOverrides = []
  /** @type {any[]} */
  let allScenes = []
  /** @type {string | null} */
  let editingSlot = null  // "mode/period" key when picker is open

  const TIME_PERIODS = ['day', 'evening', 'night']
  const PERIOD_LABELS = { day: 'Day', evening: 'Evening', night: 'Night' }

  $: currentSchedule = scheduleConfig?.[scheduleDay]

  /** @param {string} mode @param {string} period */
  function getOverride(mode, period) {
    return modeSceneOverrides.find(
      (/** @type {any} */ o) => o.mode === mode && o.time_period === period
    )
  }

  async function loadModeScenes() {
    try {
      const data = await apiGet('/api/automation/mode-scenes')
      modeSceneOverrides = data.overrides || []
    } catch {}
    if (!allScenes.length) {
      try {
        const data = await apiGet('/api/scenes')
        allScenes = data.scenes || []
      } catch {}
    }
  }

  /** @param {string} mode @param {string} period @param {any} scene */
  async function setModeScene(mode, period, scene) {
    saving = 'mode-scene'
    try {
      await apiPut(`/api/automation/mode-scenes/${mode}/${period}`, {
        scene_id: scene.id,
        scene_source: scene.source,
        scene_name: scene.display_name || scene.name,
      })
      await loadModeScenes()
    } catch {}
    editingSlot = null
    saving = null
  }

  /** @param {string} mode @param {string} period */
  async function clearModeScene(mode, period) {
    saving = 'mode-scene'
    try {
      await apiDelete(`/api/automation/mode-scenes/${mode}/${period}`)
      await loadModeScenes()
    } catch {}
    saving = null
  }

  onMount(async () => {
    try { health = await apiGet('/health') } catch {}
    try { autoConfig = await apiGet('/api/automation/config') } catch {}
    try { scheduleConfig = await apiGet('/api/automation/schedule') } catch {}
    try { modeBrightness = await apiGet('/api/automation/mode-brightness') } catch {}
    // Camera status is loaded globally in init.js and updated via WebSocket
    loadPiholeData()
    loadModeScenes()
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

  async function toggleCamera() {
    const newState = !$cameraStore?.enabled
    saving = 'camera'
    try {
      const resp = await apiPost('/api/camera/enable', { enabled: newState })
      $cameraStore = await apiGet('/api/camera/status')
    } catch {}
    saving = null
  }

  let calibrateResult = null
  async function calibrateLux() {
    saving = 'calibrate'
    calibrateResult = null
    try {
      const resp = await apiPost('/api/camera/calibrate', {})
      calibrateResult = resp
      $cameraStore = await apiGet('/api/camera/status')
    } catch (err) {
      calibrateResult = { status: 'error', detail: err?.message ?? 'failed' }
    }
    saving = null
  }

  // ----- Pi-hole DNS & Blocklist management -----

  const RECOMMENDED_LISTS = [
    { url: 'https://raw.githubusercontent.com/hagezi/dns-blocklists/main/domains/multi.txt', label: 'Hagezi Multi' },
    { url: 'https://big.oisd.nl/', label: 'OISD Full' },
    { url: 'https://v.firebog.net/hosts/AdguardDNS.txt', label: 'AdGuard DNS' },
    { url: 'https://v.firebog.net/hosts/Easyprivacy.txt', label: 'EasyPrivacy' },
    { url: 'https://v.firebog.net/hosts/Easylist.txt', label: 'EasyList' },
    { url: 'https://raw.githubusercontent.com/hagezi/dns-blocklists/main/domains/tif.txt', label: 'Hagezi TIF (Threats)' },
    { url: 'https://phishing.army/download/phishing_army_blocklist.txt', label: 'Phishing Army' },
    { url: 'https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/fake.txt', label: 'Hagezi Fake/Scam' },
    { url: 'https://raw.githubusercontent.com/hagezi/dns-blocklists/main/domains/native.winoffice.txt', label: 'Windows Telemetry' },
  ]

  const DEFAULT_DNS_HOSTS = [
    { ip: '192.168.1.210', hostname: 'homehub.local' },
    { ip: '192.168.1.210', hostname: 'pihole.local' },
    { ip: '192.168.1.50', hostname: 'hue.local' },
    { ip: '192.168.1.157', hostname: 'sonos.local' },
    { ip: '192.168.1.30', hostname: 'desktop.local' },
    { ip: '192.168.1.209', hostname: 'tablet.local' },
  ]

  /** @type {any[] | null} */
  let dnsHosts = null
  /** @type {any[] | null} */
  let blocklists = null
  let newDnsHostname = ''
  let newDnsIp = ''
  let newBlocklistUrl = ''
  let piholeAvailable = false

  async function loadPiholeData() {
    try {
      const dnsResp = await apiGet('/api/pihole/dns')
      dnsHosts = dnsResp.dns_hosts || []
      piholeAvailable = true
    } catch { dnsHosts = null }
    try {
      const listsResp = await apiGet('/api/pihole/lists')
      blocklists = listsResp.lists || []
    } catch { blocklists = null }
  }

  async function addDnsHost() {
    if (!newDnsHostname || !newDnsIp) return
    saving = 'dns-add'
    try {
      await apiPost('/api/pihole/dns', { ip: newDnsIp, hostname: newDnsHostname })
      newDnsHostname = ''
      newDnsIp = ''
      const resp = await apiGet('/api/pihole/dns')
      dnsHosts = resp.dns_hosts || []
    } catch {}
    saving = null
  }

  /** @param {{ ip: string, hostname: string }} record */
  async function deleteDnsHost(record) {
    saving = 'dns-del'
    try {
      await apiDelete(`/api/pihole/dns/${record.ip}/${record.hostname}`)
      dnsHosts = (dnsHosts || []).filter(
        (/** @type {any} */ r) => !(r.ip === record.ip && r.hostname === record.hostname)
      )
    } catch {}
    saving = null
  }

  async function addAllDefaultDns() {
    saving = 'dns-defaults'
    for (const host of DEFAULT_DNS_HOSTS) {
      const exists = (dnsHosts || []).some(
        (/** @type {any} */ r) => r.ip === host.ip && r.hostname === host.hostname
      )
      if (!exists) {
        try { await apiPost('/api/pihole/dns', host) } catch {}
      }
    }
    try {
      const resp = await apiGet('/api/pihole/dns')
      dnsHosts = resp.dns_hosts || []
    } catch {}
    saving = null
  }

  /** @param {string} url */
  async function addBlocklist(url) {
    saving = 'list-add'
    try {
      await apiPost('/api/pihole/lists', { address: url })
      const resp = await apiGet('/api/pihole/lists')
      blocklists = resp.lists || []
      newBlocklistUrl = ''
    } catch {}
    saving = null
  }

  /** @param {string} address */
  async function deleteBlocklist(address) {
    saving = 'list-del'
    try {
      await apiDelete(`/api/pihole/lists/${encodeURIComponent(address)}`)
      blocklists = (blocklists || []).filter((/** @type {any} */ l) => l.address !== address)
    } catch {}
    saving = null
  }

  async function addAllRecommendedLists() {
    saving = 'lists-recommended'
    const existingUrls = new Set((blocklists || []).map((/** @type {any} */ l) => l.address))
    for (const list of RECOMMENDED_LISTS) {
      if (!existingUrls.has(list.url)) {
        try { await apiPost('/api/pihole/lists', { address: list.url }) } catch {}
      }
    }
    try {
      const resp = await apiGet('/api/pihole/lists')
      blocklists = resp.lists || []
    } catch {}
    saving = null
  }

  /** @param {string} url */
  function getListLabel(url) {
    const rec = RECOMMENDED_LISTS.find(l => l.url === url)
    if (rec) return rec.label
    try {
      const u = new URL(url)
      const parts = u.pathname.split('/')
      return parts[parts.length - 1] || u.hostname
    } catch { return url }
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
          <span class="device-dot {health.devices?.pihole ? 'dot-green' : 'dot-red'}" />
          <span class="device-name">Pi-hole</span>
          <span class="device-detail">{health.devices?.pihole ? 'Connected' : 'Offline'}</span>
        </div>
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
            <span class="setting-label">Camera Detection</span>
            <span class="setting-hint">Latitude webcam for fast away detection (15s)</span>
          </div>
          <button
            class="toggle-btn"
            class:toggle-on={$cameraStore?.enabled}
            on:click={toggleCamera}
            disabled={saving === 'camera'}
          >
            {$cameraStore?.enabled ? 'ON' : 'OFF'}
          </button>
        </div>
        {#if $cameraStore?.enabled}
          <div class="setting-row">
            <div class="setting-info">
              <span class="setting-label">Detection</span>
            </div>
            <span class="setting-value">
              {$cameraStore.last_detection === 'present' ? 'Present' : $cameraStore.last_detection === 'absent' ? 'Absent' : 'Unknown'}
              {#if $cameraStore.confidence > 0}
                ({($cameraStore.confidence * 100).toFixed(0)}%)
              {/if}
            </span>
          </div>
          <div class="setting-row">
            <div class="setting-info">
              <span class="setting-label">Ambient Lux</span>
              <span class="setting-hint">
                {#if $cameraStore.calibrated}
                  Adapts working/relax brightness (×{($cameraStore.current_multiplier ?? 1).toFixed(2)})
                {:else}
                  Uncalibrated — auto-exposure defeats the signal
                {/if}
              </span>
            </div>
            <span class="setting-value">
              {$cameraStore.ema_lux?.toFixed(0) ?? $cameraStore.ambient_lux?.toFixed(0) ?? '--'} / 255
            </span>
          </div>
          <div class="setting-row">
            <div class="setting-info">
              <span class="setting-label">Calibrate Ambient Light</span>
              <span class="setting-hint">
                {#if calibrateResult?.status === 'ok'}
                  Calibrated: exposure {calibrateResult.exposure_value?.toFixed(2)}, lux ~{calibrateResult.measured_lux?.toFixed(0)}
                {:else if calibrateResult?.status === 'error'}
                  Failed: {calibrateResult.detail}
                {:else}
                  Run once under typical lighting
                {/if}
              </span>
            </div>
            <button
              class="toggle-btn"
              on:click={calibrateLux}
              disabled={saving === 'calibrate' || $cameraStore.paused}
            >
              {saving === 'calibrate' ? '...' : 'Calibrate'}
            </button>
          </div>
          {#if $cameraStore.paused}
            <div class="setting-row">
              <span class="setting-hint">Paused during sleeping mode</span>
            </div>
          {/if}
        {/if}

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

  <!-- Mode Lighting (scene overrides) -->
  <section class="widget">
    <h2 class="widget-title">Mode Lighting</h2>
    <p class="widget-hint">Map a Hue scene to any mode + time of day. Overrides default automation lighting.</p>
    <div class="settings-card">
      <div class="mode-scene-grid">
        <div class="ms-header"></div>
        {#each TIME_PERIODS as period}
          <div class="ms-header">{PERIOD_LABELS[period]}</div>
        {/each}
        {#each Object.entries(MODE_LABELS) as [mode, label] (mode)}
          <div class="ms-mode-label">{label}</div>
          {#each TIME_PERIODS as period}
            {@const override = getOverride(mode, period)}
            {@const slotKey = `${mode}/${period}`}
            <div class="ms-cell">
              {#if editingSlot === slotKey}
                <div class="ms-picker">
                  <button class="ms-pick-btn ms-pick-default" on:click={() => { clearModeScene(mode, period); editingSlot = null }}>
                    Default
                  </button>
                  {#each allScenes as scene (scene.id)}
                    <button class="ms-pick-btn" on:click={() => setModeScene(mode, period, scene)}>
                      {scene.display_name || scene.name}
                      <span class="ms-pick-source">{scene.source}</span>
                    </button>
                  {/each}
                </div>
              {:else if override}
                <button class="ms-cell-btn ms-cell-active" on:click={() => { editingSlot = slotKey }}>
                  {override.scene_name}
                </button>
              {:else}
                <button class="ms-cell-btn" on:click={() => { editingSlot = slotKey }}>
                  Default
                </button>
              {/if}
            </div>
          {/each}
        {/each}
      </div>
    </div>
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

  <!-- Pi-hole Local DNS -->
  {#if piholeAvailable}
  <section class="widget">
    <h2 class="widget-title">Local DNS</h2>
    <div class="settings-card">
      {#if dnsHosts && dnsHosts.length > 0}
        <div class="pihole-list">
          {#each dnsHosts as record (record.ip + record.hostname)}
            <div class="pihole-list-item">
              <div class="pihole-list-info">
                <span class="pihole-list-primary">{record.hostname}</span>
                <span class="pihole-list-secondary">{record.ip}</span>
              </div>
              <button
                class="pihole-remove-btn"
                on:click={() => deleteDnsHost(record)}
                disabled={saving === 'dns-del'}
              >x</button>
            </div>
          {/each}
        </div>
      {:else if dnsHosts}
        <div class="pihole-empty">No custom DNS records</div>
      {/if}

      <div class="pihole-add-form">
        <input
          class="pihole-input"
          type="text"
          placeholder="hostname.local"
          bind:value={newDnsHostname}
        />
        <input
          class="pihole-input pihole-input-sm"
          type="text"
          placeholder="192.168.1.x"
          bind:value={newDnsIp}
        />
        <button
          class="action-btn"
          on:click={addDnsHost}
          disabled={!newDnsHostname || !newDnsIp || saving === 'dns-add'}
        >Add</button>
      </div>

      <div class="action-row">
        <button
          class="action-btn"
          on:click={addAllDefaultDns}
          disabled={saving === 'dns-defaults'}
        >
          {saving === 'dns-defaults' ? 'Adding...' : 'Add All Devices'}
        </button>
        <span class="setting-hint">homehub, pihole, hue, sonos, desktop, tablet</span>
      </div>
    </div>
  </section>

  <!-- Pi-hole Blocklists -->
  <section class="widget">
    <h2 class="widget-title">Blocklists</h2>
    <div class="settings-card">
      {#if blocklists && blocklists.length > 0}
        <div class="pihole-list">
          {#each blocklists as list (list.address)}
            <div class="pihole-list-item">
              <div class="pihole-list-info">
                <span class="pihole-list-primary">{getListLabel(list.address)}</span>
                <span class="pihole-list-secondary pihole-list-url">{list.address}</span>
              </div>
              <button
                class="pihole-remove-btn"
                on:click={() => deleteBlocklist(list.address)}
                disabled={saving === 'list-del'}
              >x</button>
            </div>
          {/each}
        </div>
      {:else if blocklists}
        <div class="pihole-empty">No blocklists configured</div>
      {/if}

      <div class="pihole-add-form">
        <input
          class="pihole-input pihole-input-wide"
          type="url"
          placeholder="https://blocklist-url..."
          bind:value={newBlocklistUrl}
        />
        <button
          class="action-btn"
          on:click={() => addBlocklist(newBlocklistUrl)}
          disabled={!newBlocklistUrl || saving === 'list-add'}
        >Add</button>
      </div>

      <div class="action-row">
        <button
          class="action-btn"
          on:click={addAllRecommendedLists}
          disabled={saving === 'lists-recommended'}
        >
          {saving === 'lists-recommended' ? 'Adding...' : 'Add Recommended Lists'}
        </button>
        <span class="setting-hint">{RECOMMENDED_LISTS.length} curated lists (ads, malware, tracking)</span>
      </div>
    </div>
  </section>
  {/if}

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

  /* Pi-hole management */
  .pihole-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-bottom: 12px;
  }

  .pihole-list-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 6px 8px;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.03);
  }

  .pihole-list-info {
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
  }

  .pihole-list-primary {
    font-family: var(--font-body);
    font-size: 13px;
    font-weight: 500;
    color: var(--text-primary);
  }

  .pihole-list-secondary {
    font-family: var(--font-body);
    font-size: 11px;
    color: var(--text-muted);
  }

  .pihole-list-url {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 240px;
  }

  .pihole-remove-btn {
    flex-shrink: 0;
    width: 24px;
    height: 24px;
    border: none;
    border-radius: 6px;
    background: rgba(255, 60, 60, 0.15);
    color: #ff6b6b;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.2s;
  }

  .pihole-remove-btn:hover {
    background: rgba(255, 60, 60, 0.3);
  }

  .pihole-add-form {
    display: flex;
    gap: 8px;
    margin-bottom: 10px;
  }

  .pihole-input {
    flex: 1;
    padding: 6px 10px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.05);
    color: var(--text-primary);
    font-family: var(--font-body);
    font-size: 12px;
    outline: none;
    transition: border-color 0.2s;
  }

  .pihole-input:focus {
    border-color: var(--text-secondary);
  }

  .pihole-input::placeholder {
    color: var(--text-muted);
  }

  .pihole-input-sm {
    flex: 0.6;
  }

  .pihole-input-wide {
    flex: 2;
  }

  .pihole-empty {
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--text-muted);
    padding: 8px 0;
    margin-bottom: 10px;
  }

  /* Mode Lighting grid */
  .widget-hint {
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--text-muted);
    margin: -4px 0 8px;
  }

  .mode-scene-grid {
    display: grid;
    grid-template-columns: 80px repeat(3, 1fr);
    gap: 6px;
    align-items: center;
  }

  .ms-header {
    font-family: var(--font-display);
    font-size: 12px;
    text-transform: uppercase;
    color: var(--text-muted);
    text-align: center;
    padding: 4px 0;
  }

  .ms-mode-label {
    font-family: var(--font-body);
    font-size: 13px;
    font-weight: 500;
    color: var(--text-primary);
    padding: 4px 0;
  }

  .ms-cell {
    position: relative;
  }

  .ms-cell-btn {
    width: 100%;
    padding: 6px 8px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.03);
    color: var(--text-muted);
    font-family: var(--font-body);
    font-size: 11px;
    cursor: pointer;
    transition: background 0.2s, border-color 0.2s;
    text-overflow: ellipsis;
    overflow: hidden;
    white-space: nowrap;
  }

  .ms-cell-btn:hover {
    background: rgba(255, 255, 255, 0.08);
    border-color: rgba(255, 255, 255, 0.15);
  }

  .ms-cell-active {
    color: var(--text-primary);
    background: rgba(100, 180, 255, 0.1);
    border-color: rgba(100, 180, 255, 0.25);
  }

  .ms-picker {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    z-index: 20;
    max-height: 200px;
    overflow-y: auto;
    background: rgba(20, 20, 30, 0.97);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 10px;
    padding: 4px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  }

  .ms-pick-btn {
    display: flex;
    justify-content: space-between;
    align-items: center;
    width: 100%;
    padding: 6px 8px;
    border: none;
    border-radius: 6px;
    background: transparent;
    color: var(--text-primary);
    font-family: var(--font-body);
    font-size: 11px;
    cursor: pointer;
    transition: background 0.15s;
    text-align: left;
  }

  .ms-pick-btn:hover {
    background: rgba(255, 255, 255, 0.08);
  }

  .ms-pick-default {
    color: var(--text-muted);
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    margin-bottom: 2px;
  }

  .ms-pick-source {
    font-size: 9px;
    color: var(--text-muted);
    text-transform: uppercase;
    flex-shrink: 0;
    margin-left: 4px;
  }
</style>
