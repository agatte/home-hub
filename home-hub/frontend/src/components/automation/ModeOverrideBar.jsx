/**
 * ModeOverrideBar — manual mode selection buttons.
 */

const MODES = [
  { id: 'gaming', label: 'Gaming', icon: '🎮' },
  { id: 'working', label: 'Working', icon: '💻' },
  { id: 'movie', label: 'Movie', icon: '🍿' },
  { id: 'relax', label: 'Relax', icon: '🌙' },
  { id: 'social', label: 'Party', icon: '🎉' },
  { id: 'auto', label: 'Auto', icon: '✨' },
]

export function ModeOverrideBar({ currentMode, manualOverride, onOverride }) {
  return (
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
  )
}
