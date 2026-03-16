import { createContext, useContext, useState, useCallback, useEffect, useMemo } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'

const LightsContext = createContext(null)
const SonosContext = createContext(null)
const AutomationContext = createContext(null)
const MusicContext = createContext(null)
const ConnectionContext = createContext(null)

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
    social_style: 'color_cycle',
  })
  const [musicSuggestion, setMusicSuggestion] = useState(null)
  const [musicAutoPlayed, setMusicAutoPlayed] = useState(null)

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
      case 'music_suggestion':
        setMusicSuggestion(data)
        break
      case 'music_auto_played':
        setMusicAutoPlayed(data)
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
    // Optimistic update — highlight the button immediately
    setAutomationMode((prev) => ({
      ...prev,
      mode: mode === 'auto' ? prev.mode : mode,
      manual_override: mode !== 'auto',
    }))
    await fetch('/api/automation/override', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    })
  }, [])

  const setSocialStyle = useCallback(async (style) => {
    await fetch('/api/automation/social-style', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ style }),
    })
  }, [])

  const dismissMusicSuggestion = useCallback(() => {
    setMusicSuggestion(null)
  }, [])

  const acceptMusicSuggestion = useCallback(async () => {
    if (!musicSuggestion) return
    try {
      await fetch(`/api/sonos/favorites/${encodeURIComponent(musicSuggestion.title)}/play`, {
        method: 'POST',
      })
    } catch { /* ignore */ }
    setMusicSuggestion(null)
  }, [musicSuggestion])

  // Auto-clear music suggestion after 15s
  useEffect(() => {
    if (!musicSuggestion) return
    const timer = setTimeout(() => setMusicSuggestion(null), 15000)
    return () => clearTimeout(timer)
  }, [musicSuggestion])

  // Auto-clear music auto-played toast after 5s
  useEffect(() => {
    if (!musicAutoPlayed) return
    const timer = setTimeout(() => setMusicAutoPlayed(null), 5000)
    return () => clearTimeout(timer)
  }, [musicAutoPlayed])

  // Split into separate context values so updates to one don't re-render consumers of another
  const lightsValue = useMemo(() => ({ lights, setLight }), [lights, setLight])
  const sonosValue = useMemo(() => ({ sonos, sonosCommand, speakText }), [sonos, sonosCommand, speakText])
  const automationValue = useMemo(
    () => ({ automationMode, setManualMode, setSocialStyle, activateScene }),
    [automationMode, setManualMode, setSocialStyle, activateScene]
  )
  const musicValue = useMemo(
    () => ({ musicSuggestion, musicAutoPlayed, dismissMusicSuggestion, acceptMusicSuggestion }),
    [musicSuggestion, musicAutoPlayed, dismissMusicSuggestion, acceptMusicSuggestion]
  )
  const connectionValue = useMemo(
    () => ({ connected, deviceStatus }),
    [connected, deviceStatus]
  )

  return (
    <ConnectionContext.Provider value={connectionValue}>
      <AutomationContext.Provider value={automationValue}>
        <MusicContext.Provider value={musicValue}>
          <SonosContext.Provider value={sonosValue}>
            <LightsContext.Provider value={lightsValue}>
              {children}
            </LightsContext.Provider>
          </SonosContext.Provider>
        </MusicContext.Provider>
      </AutomationContext.Provider>
    </ConnectionContext.Provider>
  )
}

export function useLights() {
  const context = useContext(LightsContext)
  if (!context) throw new Error('useLights must be used within HubProvider')
  return context
}

export function useSonos() {
  const context = useContext(SonosContext)
  if (!context) throw new Error('useSonos must be used within HubProvider')
  return context
}

export function useAutomation() {
  const context = useContext(AutomationContext)
  if (!context) throw new Error('useAutomation must be used within HubProvider')
  return context
}

export function useMusic() {
  const context = useContext(MusicContext)
  if (!context) throw new Error('useMusic must be used within HubProvider')
  return context
}

export function useConnection() {
  const context = useContext(ConnectionContext)
  if (!context) throw new Error('useConnection must be used within HubProvider')
  return context
}

// Backward-compatible hook — returns everything (still causes full re-renders if used)
export function useHub() {
  const { lights, setLight } = useLights()
  const { sonos, sonosCommand, speakText } = useSonos()
  const { automationMode, setManualMode, setSocialStyle, activateScene } = useAutomation()
  const { connected, deviceStatus } = useConnection()
  return {
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
    setSocialStyle,
  }
}
