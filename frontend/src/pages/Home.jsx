import { useState, useEffect } from 'react'
import { useLights, useAutomation, useSonos } from '../context/HubContext'
import { ModeIndicator } from '../components/automation/ModeIndicator'
import { ModeOverrideBar } from '../components/automation/ModeOverrideBar'
import { RoutineCard } from '../components/automation/RoutineCard'
import { LightGrid } from '../components/lights/LightGrid'
import { NativeSceneGrid } from '../components/lights/NativeSceneGrid'
import { SceneButton } from '../components/lights/SceneButton'
import { SonosCard } from '../components/sonos/SonosCard'
import { MusicSuggestionToast } from '../components/music/MusicSuggestionToast'
import { QuickActions } from '../components/layout/QuickActions'

export function Home() {
  const { lights, setLight } = useLights()
  const { sonos, sonosCommand } = useSonos()
  const {
    automationMode,
    setManualMode,
    setSocialStyle,
    activateScene,
  } = useAutomation()
  const [scenes, setScenes] = useState([])

  useEffect(() => {
    fetch('/api/scenes')
      .then((r) => r.json())
      .then((data) => {
        const presets = (data.scenes || []).filter((s) => s.source === 'preset')
        setScenes(presets)
      })
      .catch(() => {})
  }, [])

  return (
    <main className="home-page">
      <QuickActions currentMode={automationMode.mode} onMode={setManualMode} />

      <div className="widget-grid">
        <section className="widget widget-mode">
          <h2 className="widget-title">Mode</h2>
          <ModeIndicator
            mode={automationMode.mode}
            source={automationMode.source}
            manualOverride={automationMode.manual_override}
            socialStyle={automationMode.social_style}
          />
          <ModeOverrideBar
            currentMode={automationMode.mode}
            manualOverride={automationMode.manual_override}
            socialStyle={automationMode.social_style}
            onOverride={setManualMode}
            onSocialStyle={setSocialStyle}
          />
        </section>

        <section className="widget widget-sonos">
          <h2 className="widget-title">Sonos</h2>
          <SonosCard sonos={sonos} onCommand={sonosCommand} />
        </section>

        <section className="widget widget-lights">
          <h2 className="widget-title">Lights</h2>
          <LightGrid lights={lights} onUpdate={setLight} />
          <div className="scene-bar">
            {scenes.map((scene) => (
              <SceneButton
                key={scene.id || scene.name}
                name={scene.id || scene.name}
                displayName={scene.display_name}
                onActivate={activateScene}
              />
            ))}
          </div>
          <NativeSceneGrid onActivateScene={activateScene} />
        </section>

        <section className="widget widget-routines widget-routines-full">
          <h2 className="widget-title">Routines</h2>
          <RoutineCard />
        </section>
      </div>

      <MusicSuggestionToast />
    </main>
  )
}
