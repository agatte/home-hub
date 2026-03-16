/**
 * ModeOverrideBar — manual mode selection buttons + party sub-mode selector.
 */

const MODES = [
  { id: 'gaming', label: 'Gaming', icon: '🎮' },
  { id: 'working', label: 'Working', icon: '💻' },
  { id: 'watching', label: 'Watching', icon: '🎬' },
  { id: 'movie', label: 'Movie', icon: '🍿' },
  { id: 'relax', label: 'Relax', icon: '🌙' },
  { id: 'social', label: 'Party', icon: '🎉' },
  { id: 'auto', label: 'Auto', icon: '✨' },
]

const SOCIAL_STYLES = [
  { id: 'color_cycle', label: 'Color Cycle', icon: '🌈' },
  { id: 'club', label: 'Club', icon: '💜' },
  { id: 'rave', label: 'Rave', icon: '⚡' },
  { id: 'fire_and_ice', label: 'Fire & Ice', icon: '🔥' },
]

import { memo } from 'react'

export const ModeOverrideBar = memo(function ModeOverrideBar({
  currentMode,
  manualOverride,
  socialStyle,
  onOverride,
  onSocialStyle,
}) {
  const showSocialStyles = currentMode === 'social'

  return (
    <div>
      <div className="mode-override-bar">
        {MODES.map((mode) => {
          const isActive =
            mode.id === 'auto'
              ? !manualOverride
              : manualOverride && currentMode === mode.id

          return (
            <button
              key={mode.id}
              className={`mode-btn ${isActive ? 'mode-btn-active' : ''}`}
              onClick={() => onOverride(mode.id)}
            >
              <span className="mode-btn-icon">{mode.icon}</span>
              <span className="mode-btn-label">{mode.label}</span>
            </button>
          )
        })}
      </div>
      {showSocialStyles && (
        <div className="social-style-bar">
          {SOCIAL_STYLES.map((style) => (
            <button
              key={style.id}
              className={`social-style-btn ${
                socialStyle === style.id ? 'social-style-btn-active' : ''
              }`}
              onClick={() => onSocialStyle(style.id)}
            >
              <span className="mode-btn-icon">{style.icon}</span>
              <span className="mode-btn-label">{style.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
})
