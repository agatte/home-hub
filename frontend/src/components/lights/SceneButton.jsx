import { memo } from 'react'

const SCENE_ICONS = {
  movie_night: '🎬',
  bright: '☀️',
  colts_blue: '🏈',
  relax: '🌙',
  all_off: '⏻',
  warm_white: '💡',
  daylight: '🌤',
}

export const SceneButton = memo(function SceneButton({ name, displayName, onActivate }) {
  return (
    <button className="scene-btn" onClick={() => onActivate(name)}>
      <span className="scene-icon">{SCENE_ICONS[name] || '💡'}</span>
      <span className="scene-name">{displayName}</span>
    </button>
  )
})
