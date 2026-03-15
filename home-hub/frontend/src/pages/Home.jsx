import { useState, useEffect } from 'react'
import { useHub } from '../context/HubContext'
import { LightGrid } from '../components/lights/LightGrid'
import { SceneButton } from '../components/lights/SceneButton'
import { SonosCard } from '../components/sonos/SonosCard'

export function Home() {
  const { lights, setLight, sonos, sonosCommand, activateScene } = useHub()
  const [scenes, setScenes] = useState([])

  useEffect(() => {
    fetch('/api/scenes')
      .then((r) => r.json())
      .then((data) => setScenes(data.scenes || []))
      .catch(() => {})
  }, [])

  return (
    <main className="home-page">
      <section className="section">
        <h2 className="section-title">Lights</h2>
        <LightGrid lights={lights} onUpdate={setLight} />
        <div className="scene-bar">
          {scenes.map((scene) => (
            <SceneButton
              key={scene.name}
              name={scene.name}
              displayName={scene.display_name}
              onActivate={activateScene}
            />
          ))}
        </div>
      </section>

      <section className="section">
        <h2 className="section-title">Sonos</h2>
        <SonosCard sonos={sonos} onCommand={sonosCommand} />
      </section>
    </main>
  )
}
