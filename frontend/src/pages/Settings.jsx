import { useState, useEffect, useCallback } from 'react'
import { useHub } from '../context/HubContext'
import { Slider } from '../components/common/Slider'

const MODE_LABELS = {
  gaming: 'Gaming',
  working: 'Working',
  watching: 'Watching',
  relax: 'Relax',
  movie: 'Movie',
  social: 'Social',
}

const RAMP_OPTIONS = [30, 60, 90, 120]

export function Settings() {
  const { connected, deviceStatus } = useHub()
  const [health, setHealth] = useState(null)
  const [autoConfig, setAutoConfig] = useState(null)
  const [routineConfig, setRoutineConfig] = useState(null)
  const [scheduleConfig, setScheduleConfig] = useState(null)
  const [scheduleDay, setScheduleDay] = useState('weekday')
  const [modeBrightness, setModeBrightness] = useState(null)
  const [winddownConfig, setWinddownConfig] = useState(null)
  const [saving, setSaving] = useState(null)

  // Fetch all settings on mount
  useEffect(() => {
    fetch('/health')
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => {})

    fetch('/api/automation/config')
      .then((r) => r.json())
      .then(setAutoConfig)
      .catch(() => {})

    fetch('/api/automation/schedule')
      .then((r) => r.json())
      .then(setScheduleConfig)
      .catch(() => {})

    fetch('/api/automation/mode-brightness')
      .then((r) => r.json())
      .then(setModeBrightness)
      .catch(() => {})

    fetch('/api/routines')
      .then((r) => r.json())
      .then((data) => {
        const morning = (data.routines || []).find((r) => r.name === 'morning_routine')
        if (morning) {
          const [h, m] = morning.time.split(':').map(Number)
          setRoutineConfig({
            hour: h,
            minute: m,
            enabled: morning.enabled,
            volume: morning.volume ?? 40,
          })
        }
        const winddown = (data.routines || []).find((r) => r.name === 'winddown_routine')
        if (winddown) {
          const [wh, wm] = winddown.time.split(':').map(Number)
          setWinddownConfig({
            hour: wh,
            minute: wm,
            enabled: winddown.enabled,
            volume: winddown.volume ?? 20,
            activate_candlelight: winddown.activate_candlelight ?? true,
            weekdays_only: winddown.weekdays_only ?? false,
          })
        } else {
          setWinddownConfig({
            hour: 21, minute: 0, enabled: false,
            volume: 20, activate_candlelight: true, weekdays_only: false,
          })
        }
      })
      .catch(() => {})
  }, [])

  const saveAutoConfig = useCallback(
    async (updates) => {
      const next = { ...autoConfig, ...updates }
      setAutoConfig(next)
      setSaving('auto')
      try {
        await fetch('/api/automation/config', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(next),
        })
      } catch {}
      setSaving(null)
    },
    [autoConfig]
  )

  const saveRoutineConfig = useCallback(
    async (updates) => {
      const next = { ...routineConfig, ...updates }
      setRoutineConfig(next)
      setSaving('routine')
      try {
        await fetch('/api/routines/morning/config', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(next),
        })
      } catch {}
      setSaving(null)
    },
    [routineConfig]
  )

  const saveScheduleConfig = useCallback(
    async (dayType, updates) => {
      const next = {
        ...scheduleConfig,
        [dayType]: { ...scheduleConfig[dayType], ...updates },
      }
      setScheduleConfig(next)
      setSaving('schedule')
      try {
        await fetch('/api/automation/schedule', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(next),
        })
      } catch {}
      setSaving(null)
    },
    [scheduleConfig]
  )

  const saveModeBrightness = useCallback(
    async (updates) => {
      const next = { ...modeBrightness, ...updates }
      setModeBrightness(next)
      setSaving('brightness')
      try {
        await fetch('/api/automation/mode-brightness', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(next),
        })
      } catch {}
      setSaving(null)
    },
    [modeBrightness]
  )

  const saveWinddownConfig = useCallback(
    async (updates) => {
      const next = { ...winddownConfig, ...updates }
      setWinddownConfig(next)
      setSaving('winddown')
      try {
        await fetch('/api/routines/winddown/config', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(next),
        })
      } catch {}
      setSaving(null)
    },
    [winddownConfig]
  )

  const testTTS = useCallback(async () => {
    setSaving('tts')
    try {
      await fetch('/api/sonos/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: 'Home Hub is connected and working.', volume: 10 }),
      })
    } catch {}
    setSaving(null)
  }, [])

  const testWinddown = useCallback(async () => {
    setSaving('winddown-test')
    try {
      await fetch('/api/routines/winddown/test', { method: 'POST' })
    } catch {}
    setSaving(null)
  }, [])

  const currentSchedule = scheduleConfig?.[scheduleDay]

  return (
    <main className="settings-page">
      {/* Device Status */}
      <section className="section">
        <h2 className="section-title">Device Status</h2>
        <div className="settings-card">
          <div className="device-row">
            <span className={`device-dot ${connected ? 'dot-green' : 'dot-red'}`} />
            <span className="device-name">Server</span>
            <span className="device-detail">{connected ? 'Connected' : 'Disconnected'}</span>
          </div>
          <div className="device-row">
            <span className={`device-dot ${deviceStatus.hue ? 'dot-green' : 'dot-red'}`} />
            <span className="device-name">Hue Bridge</span>
            <span className="device-detail">{deviceStatus.hue ? 'Connected' : 'Offline'}</span>
          </div>
          <div className="device-row">
            <span className={`device-dot ${deviceStatus.sonos ? 'dot-green' : 'dot-red'}`} />
            <span className="device-name">Sonos</span>
            <span className="device-detail">{deviceStatus.sonos ? 'Connected' : 'Offline'}</span>
          </div>
          {health && (
            <div className="device-row">
              <span className="device-dot dot-blue" />
              <span className="device-name">WebSocket Clients</span>
              <span className="device-detail">{health.websocket_clients}</span>
            </div>
          )}
        </div>
      </section>

      {/* Automation Settings */}
      <section className="section">
        <h2 className="section-title">Automation</h2>
        {autoConfig && (
          <div className="settings-card">
            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-label">Automation Enabled</span>
                <span className="setting-hint">Auto-detect gaming, working, etc.</span>
              </div>
              <button
                className={`toggle-btn ${autoConfig.enabled ? 'toggle-on' : ''}`}
                onClick={() => saveAutoConfig({ enabled: !autoConfig.enabled })}
              >
                {autoConfig.enabled ? 'ON' : 'OFF'}
              </button>
            </div>

            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-label">Override Timeout</span>
                <span className="setting-hint">Hours before manual mode auto-clears</span>
              </div>
              <div className="setting-stepper">
                <button
                  className="stepper-btn"
                  onClick={() =>
                    saveAutoConfig({
                      override_timeout_hours: Math.max(1, autoConfig.override_timeout_hours - 1),
                    })
                  }
                >
                  -
                </button>
                <span className="stepper-value">{autoConfig.override_timeout_hours}h</span>
                <button
                  className="stepper-btn"
                  onClick={() =>
                    saveAutoConfig({
                      override_timeout_hours: Math.min(12, autoConfig.override_timeout_hours + 1),
                    })
                  }
                >
                  +
                </button>
              </div>
            </div>

          </div>
        )}
      </section>

      {/* Light Schedule */}
      <section className="section">
        <h2 className="section-title">Light Schedule</h2>
        {scheduleConfig && currentSchedule && (
          <div className="settings-card">
            <div className="schedule-tab-row">
              <button
                className={`schedule-tab ${scheduleDay === 'weekday' ? 'schedule-tab-active' : ''}`}
                onClick={() => setScheduleDay('weekday')}
              >
                Weekday
              </button>
              <button
                className={`schedule-tab ${scheduleDay === 'weekend' ? 'schedule-tab-active' : ''}`}
                onClick={() => setScheduleDay('weekend')}
              >
                Weekend
              </button>
            </div>

            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-label">Wake-up</span>
                <span className="setting-hint">Lights turn on (dim warm)</span>
              </div>
              <input
                type="time"
                className="setting-time"
                value={`${String(currentSchedule.wake_hour).padStart(2, '0')}:00`}
                onChange={(e) => {
                  const h = parseInt(e.target.value.split(':')[0])
                  saveScheduleConfig(scheduleDay, { wake_hour: h })
                }}
              />
            </div>

            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-label">Morning Ramp</span>
                <span className="setting-hint">Gradual brighten duration</span>
              </div>
              <div className="setting-stepper">
                <button
                  className="stepper-btn"
                  onClick={() => {
                    const idx = RAMP_OPTIONS.indexOf(currentSchedule.ramp_duration_minutes)
                    if (idx > 0) saveScheduleConfig(scheduleDay, { ramp_duration_minutes: RAMP_OPTIONS[idx - 1] })
                  }}
                >
                  -
                </button>
                <span className="stepper-value">{currentSchedule.ramp_duration_minutes}m</span>
                <button
                  className="stepper-btn"
                  onClick={() => {
                    const idx = RAMP_OPTIONS.indexOf(currentSchedule.ramp_duration_minutes)
                    if (idx < RAMP_OPTIONS.length - 1) saveScheduleConfig(scheduleDay, { ramp_duration_minutes: RAMP_OPTIONS[idx + 1] })
                  }}
                >
                  +
                </button>
              </div>
            </div>

            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-label">Away Hours</span>
                <span className="setting-hint">Lights off (at work)</span>
              </div>
              <button
                className={`toggle-btn ${currentSchedule.away_start_hour != null ? 'toggle-on' : ''}`}
                onClick={() => {
                  if (currentSchedule.away_start_hour != null) {
                    saveScheduleConfig(scheduleDay, { away_start_hour: null, away_end_hour: null })
                  } else {
                    saveScheduleConfig(scheduleDay, { away_start_hour: 7, away_end_hour: 18 })
                  }
                }}
              >
                {currentSchedule.away_start_hour != null ? 'ON' : 'OFF'}
              </button>
            </div>
            {currentSchedule.away_start_hour != null && (
              <div className="setting-row">
                <div className="setting-info">
                  <span className="setting-hint">Leave / Return</span>
                </div>
                <div className="setting-time-pair">
                  <input
                    type="time"
                    className="setting-time"
                    value={`${String(currentSchedule.away_start_hour).padStart(2, '0')}:00`}
                    onChange={(e) => {
                      const h = parseInt(e.target.value.split(':')[0])
                      saveScheduleConfig(scheduleDay, { away_start_hour: h })
                    }}
                  />
                  <span className="setting-time-sep">-</span>
                  <input
                    type="time"
                    className="setting-time"
                    value={`${String(currentSchedule.away_end_hour).padStart(2, '0')}:00`}
                    onChange={(e) => {
                      const h = parseInt(e.target.value.split(':')[0])
                      saveScheduleConfig(scheduleDay, { away_end_hour: h })
                    }}
                  />
                </div>
              </div>
            )}

            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-label">Evening</span>
                <span className="setting-hint">Warm evening lighting starts</span>
              </div>
              <input
                type="time"
                className="setting-time"
                value={`${String(currentSchedule.evening_start_hour).padStart(2, '0')}:00`}
                onChange={(e) => {
                  const h = parseInt(e.target.value.split(':')[0])
                  saveScheduleConfig(scheduleDay, { evening_start_hour: h })
                }}
              />
            </div>

            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-label">Wind-down</span>
                <span className="setting-hint">Dim lighting starts</span>
              </div>
              <input
                type="time"
                className="setting-time"
                value={`${String(currentSchedule.winddown_start_hour).padStart(2, '0')}:00`}
                onChange={(e) => {
                  const h = parseInt(e.target.value.split(':')[0])
                  saveScheduleConfig(scheduleDay, { winddown_start_hour: h })
                }}
              />
            </div>
          </div>
        )}
      </section>

      {/* Mode Brightness */}
      <section className="section">
        <h2 className="section-title">Mode Brightness</h2>
        {modeBrightness && (
          <div className="settings-card">
            {Object.entries(MODE_LABELS).map(([mode, label]) => (
              <div className="setting-row" key={mode}>
                <div className="setting-info">
                  <span className="setting-label">{label}</span>
                  <span className="setting-hint">{Math.round((modeBrightness[mode] ?? 1.0) * 100)}%</span>
                </div>
                <div className="setting-slider-wrap">
                  <Slider
                    value={Math.round((modeBrightness[mode] ?? 1.0) * 100)}
                    min={30}
                    max={150}
                    onChange={(v) => saveModeBrightness({ [mode]: v / 100 })}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Morning Routine */}
      <section className="section">
        <h2 className="section-title">Morning Routine</h2>
        {routineConfig && (
          <div className="settings-card">
            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-label">Enabled</span>
                <span className="setting-hint">Weather + traffic TTS at scheduled time</span>
              </div>
              <button
                className={`toggle-btn ${routineConfig.enabled ? 'toggle-on' : ''}`}
                onClick={() => saveRoutineConfig({ enabled: !routineConfig.enabled })}
              >
                {routineConfig.enabled ? 'ON' : 'OFF'}
              </button>
            </div>

            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-label">Time</span>
                <span className="setting-hint">Weekdays only (Mon-Fri)</span>
              </div>
              <input
                type="time"
                className="setting-time"
                value={`${String(routineConfig.hour).padStart(2, '0')}:${String(routineConfig.minute).padStart(2, '0')}`}
                onChange={(e) => {
                  const [h, m] = e.target.value.split(':').map(Number)
                  saveRoutineConfig({ hour: h, minute: m })
                }}
              />
            </div>

            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-label">Volume</span>
              </div>
              <div className="setting-slider-wrap">
                <Slider
                  value={routineConfig.volume}
                  min={10}
                  max={100}
                  onChange={(v) => saveRoutineConfig({ volume: v })}
                />
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Evening Wind-Down */}
      <section className="section">
        <h2 className="section-title">Evening Wind-Down</h2>
        {winddownConfig && (
          <div className="settings-card">
            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-label">Enabled</span>
                <span className="setting-hint">Dim lights, lower volume, candlelight</span>
              </div>
              <button
                className={`toggle-btn ${winddownConfig.enabled ? 'toggle-on' : ''}`}
                onClick={() => saveWinddownConfig({ enabled: !winddownConfig.enabled })}
              >
                {winddownConfig.enabled ? 'ON' : 'OFF'}
              </button>
            </div>

            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-label">Time</span>
              </div>
              <input
                type="time"
                className="setting-time"
                value={`${String(winddownConfig.hour).padStart(2, '0')}:${String(winddownConfig.minute).padStart(2, '0')}`}
                onChange={(e) => {
                  const [h, m] = e.target.value.split(':').map(Number)
                  saveWinddownConfig({ hour: h, minute: m })
                }}
              />
            </div>

            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-label">Volume</span>
                <span className="setting-hint">Sonos volume during wind-down</span>
              </div>
              <div className="setting-slider-wrap">
                <Slider
                  value={winddownConfig.volume}
                  min={5}
                  max={50}
                  onChange={(v) => saveWinddownConfig({ volume: v })}
                />
              </div>
            </div>

            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-label">Candlelight</span>
                <span className="setting-hint">Activate Hue candlelight effect</span>
              </div>
              <button
                className={`toggle-btn ${winddownConfig.activate_candlelight ? 'toggle-on' : ''}`}
                onClick={() => saveWinddownConfig({ activate_candlelight: !winddownConfig.activate_candlelight })}
              >
                {winddownConfig.activate_candlelight ? 'ON' : 'OFF'}
              </button>
            </div>

            <div className="setting-row">
              <div className="setting-info">
                <span className="setting-label">Weekdays Only</span>
              </div>
              <button
                className={`toggle-btn ${winddownConfig.weekdays_only ? 'toggle-on' : ''}`}
                onClick={() => saveWinddownConfig({ weekdays_only: !winddownConfig.weekdays_only })}
              >
                {winddownConfig.weekdays_only ? 'ON' : 'OFF'}
              </button>
            </div>

            <div className="action-row">
              <button
                className="action-btn"
                onClick={testWinddown}
                disabled={saving === 'winddown-test'}
              >
                {saving === 'winddown-test' ? 'Running...' : 'Test Wind-Down'}
              </button>
            </div>
          </div>
        )}
      </section>

      {/* Quick Actions */}
      <section className="section">
        <h2 className="section-title">Quick Actions</h2>
        <div className="settings-card">
          <div className="action-row">
            <button className="action-btn" onClick={testTTS} disabled={saving === 'tts'}>
              {saving === 'tts' ? 'Speaking...' : 'Test TTS'}
            </button>
            <span className="setting-hint">Play a test message on Sonos</span>
          </div>
        </div>
      </section>

      {saving && <div className="settings-saving">Saving...</div>}
    </main>
  )
}
