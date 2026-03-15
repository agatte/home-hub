import { useState, useEffect } from 'react'
import { useHub } from '../context/HubContext'
import { ModeIndicator } from '../components/automation/ModeIndicator'
import { ModeOverrideBar } from '../components/automation/ModeOverrideBar'
import { RoutineCard } from '../components/automation/RoutineCard'
import { LightGrid } from '../components/lights/LightGrid'
import { NativeSceneGrid } from '../components/lights/NativeSceneGrid'
import { SceneButton } from '../components/lights/SceneButton'
import { SonosCard } from '../components/sonos/SonosCard'

export function Home() {
  const {
    lights,
    setLight,
    sonos,
    sonosCommand,
    activateScene,
    automationMode,
    setManualMode,
  } = useHub()
  const [scenes, setScenes] = useState([])

  useEffect(() => {
    fetch('/api/scenes')
      .then((r) => r.json())
      .then((data) => {
        // Only show presets in the quick bar, bridge scenes go in NativeSceneGrid
        const presets = (data.scenes || []).filter((s) => s.source === 'preset')
        setScenes(presets)
      })
      .catch(() => {})
  }, [])

  return (
    <main className="home-page">
      {/* Automation status */}
      <section className="section">
        <h2 className="section-title">Mode</h2>
        <ModeIndicator
          mode={automationMode.mode}
          source={automationMode.source}
          manualOverride={automationMode.manual_override}
        />
        <ModeOverrideBar
          currentMode={automationMode.mode}
          manualOverride={automationMode.manual_override}
          onOverride={setManualMode}
        />
      </section>

      {/* Lights */}
      <section className="section">
        <h2 className="section-title">Lights</h2>
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

      {/* Sonos */}
      <section className="section">
        <h2 className="section-title">Sonos</h2>
        <SonosCard sonos={sonos} onCommand={sonosCommand} />
      </section>

      {/* Routines */}
      <section className="section">
        <h2 className="section-title">Routines</h2>
        <RoutineCard />
      </section>
    </main>
  )
}
