import { createContext, useContext, useState, useCallback, useEffect } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'

const HubContext = createContext(null)

export function HubProvider({ children }) {
  const [lights, setLights] = useState({})
  const [sonos, setSonos] = useState({
    state: 'STOPPED',
    track: '',
    artist: '',
    album: '',
    art_url: '',
    volume: 0,
    mute: false,
  })
  const [deviceStatus, setDeviceStatus] = useState({ hue: false, sonos: false })
  const [automationMode, setAutomationMode] = useState({
    mode: 'idle',
    source: 'time',
    manual_override: false,
  })

  const handleMessage = useCallback((message) => {
    const { type, data } = message

    switch (type) {
      case 'light_update':
        setLights((prev) => ({ ...prev, [data.light_id]: data }))
        break
      case 'sonos_update':
        setSonos(data)
        break
      case 'connection_status':
        setDeviceStatus(data)
        break
      case 'mode_update':
        setAutomationMode(data)
        break
      default:
        break
    }
  }, [])

  const { connected, send } = useWebSocket(handleMessage)

  // Fetch initial state on mount
  useEffect(() => {
    fetch('/api/lights')
      .then((r) => r.json())
      .then((data) => {
        const map = {}
        data.forEach((light) => {
          map[light.light_id] = light
        })
        setLights(map)
      })
      .catch(() => {})

    fetch('/api/sonos/status')
      .then((r) => r.json())
      .then(setSonos)
      .catch(() => {})

    fetch('/api/automation/status')
      .then((r) => r.json())
      .then((data) =>
        setAutomationMode({
          mode: data.current_mode,
          source: data.mode_source,
          manual_override: data.manual_override,
        })
      )
      .catch(() => {})
  }, [])

  const setLight = useCallback(
    (lightId, state) => {
      send('light_command', { light_id: lightId, ...state })
      // Optimistic update
      setLights((prev) => ({
        ...prev,
        [lightId]: { ...prev[lightId], ...state },
      }))
    },
    [send]
  )

  const sonosCommand = useCallback(
    (action, params = {}) => {
      send('sonos_command', { action, ...params })
    },
    [send]
  )

  const activateScene = useCallback(async (sceneId) => {
    await fetch(`/api/scenes/${sceneId}/activate`, { method: 'POST' })
  }, [])

  const speakText = useCallback(async (text, volume) => {
    await fetch('/api/sonos/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, volume }),
    })
  }, [])

  const setManualMode = useCallback(async (mode) => {
    await fetch('/api/automation/override', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    })
  }, [])

  return (
    <HubContext.Provider
      value={{
        connected,
        deviceStatus,
        lights,
        setLight,
        sonos,
        sonosCommand,
        activateScene,
        speakText,
        automationMode,
        setManualMode,
      }}
    >
      {children}
    </HubContext.Provider>
  )
}

export function useHub() {
  const context = useContext(HubContext)
  if (!context) throw new Error('useHub must be used within HubProvider')
  return context
}
