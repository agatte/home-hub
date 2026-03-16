import { useState, useEffect, useCallback } from 'react'
import { useHub } from '../context/HubContext'
import { Slider } from '../components/common/Slider'


export function Settings() {
  const { connected, deviceStatus } = useHub()
  const [health, setHealth] = useState(null)
  const [autoConfig, setAutoConfig] = useState(null)
  const [routineConfig, setRoutineConfig] = useState(null)
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

    fetch('/api/routines')
      .then((r) => r.json())
      .then((data) => {
        const morning = (data.routines || []).find((r) => r.name === 'morning_routine')
        if (morning) {
          setRoutineConfig({
            hour: morning.hour,
            minute: morning.minute,
            enabled: morning.enabled,
            volume: 10, // Default, not returned by GET
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
