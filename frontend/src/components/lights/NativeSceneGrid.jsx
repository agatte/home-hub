/**
 * NativeSceneGrid — displays native Hue bridge scenes and dynamic effects.
 */
import { useState, useEffect, memo } from 'react'

export const NativeSceneGrid = memo(function NativeSceneGrid({ onActivateScene }) {
  const [bridgeScenes, setBridgeScenes] = useState([])
  const [effects, setEffects] = useState([])
  const [activeEffect, setActiveEffect] = useState(null)

  useEffect(() => {
    // Fetch native bridge scenes
    fetch('/api/scenes')
      .then((r) => r.json())
      .then((data) => {
        const scenes = (data.scenes || []).filter((s) => s.source === 'bridge')
        // Deduplicate by name — group scenes that exist in multiple rooms
        const grouped = new Map()
        for (const scene of scenes) {
          if (!grouped.has(scene.name)) {
            grouped.set(scene.name, { ...scene, ids: [scene.id] })
          } else {
            grouped.get(scene.name).ids.push(scene.id)
          }
        }
        setBridgeScenes(Array.from(grouped.values()))
      })
      .catch(() => {})

    // Fetch available effects
    fetch('/api/scenes/effects')
      .then((r) => r.json())
      .then((data) => setEffects(data.effects || []))
      .catch(() => {})
  }, [])

  const activateEffect = async (effectName) => {
    const endpoint = effectName === activeEffect ? 'stop' : effectName
    try {
      await fetch(`/api/scenes/effects/${endpoint}`, { method: 'POST' })
      setActiveEffect(effectName === activeEffect ? null : effectName)
    } catch {
      // ignore
    }
  }

  if (bridgeScenes.length === 0 && effects.length === 0) {
    return null
  }

  return (
    <div className="native-scene-section">
      {bridgeScenes.length > 0 && (
        <>
          <h3 className="subsection-title">Hue Scenes</h3>
          <div className="scene-bar">
            {bridgeScenes.map((scene) => (
              <button
                key={scene.id}
                className="scene-btn"
                onClick={() => scene.ids.forEach((id) => onActivateScene(id))}
              >
                <span className="scene-name">{scene.name}</span>
              </button>
            ))}
          </div>
        </>
      )}

      {effects.length > 0 && (
        <>
          <h3 className="subsection-title">Effects</h3>
          <div className="scene-bar">
            {effects.map((effect) => (
              <button
                key={effect.name}
                className={`scene-btn ${activeEffect === effect.name ? 'scene-btn-active' : ''}`}
                onClick={() => activateEffect(effect.name)}
                title={effect.description}
              >
                <span className="scene-name">{effect.display_name}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
})
