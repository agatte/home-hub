/**
 * ModeIndicator — displays the current automation mode with visual feedback.
 */

const MODE_CONFIG = {
  gaming: { label: 'Gaming', color: '#4a6cf7', icon: '🎮' },
  working: { label: 'Working', color: '#34d399', icon: '💻' },
  watching: { label: 'Watching', color: '#fbbf24', icon: '🎬' },
  social: { label: 'Social', color: '#f472b6', icon: '🎉' },
  relax: { label: 'Relax', color: '#a78bfa', icon: '🌙' },
  movie: { label: 'Movie', color: '#fbbf24', icon: '🍿' },
  idle: { label: 'Idle', color: '#5c5e6a', icon: '💤' },
  away: { label: 'Away', color: '#5c5e6a', icon: '🚪' },
}

export function ModeIndicator({ mode, source, manualOverride }) {
  const config = MODE_CONFIG[mode] || MODE_CONFIG.idle

  return (
    <div className="mode-indicator">
      <span className="mode-icon">{config.icon}</span>
      <div className="mode-info">
        <span className="mode-label" style={{ color: config.color }}>
          {config.label}
        </span>
        <span className="mode-source">
          {manualOverride ? 'Manual' : source === 'time' ? 'Auto (time)' : `Auto (${source})`}
        </span>
      </div>
      <div
        className="mode-dot"
        style={{ background: config.color, boxShadow: `0 0 8px ${config.color}` }}
      />
    </div>
  )
}
