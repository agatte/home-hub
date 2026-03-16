/**
 * ModeIndicator — displays the current automation mode with visual feedback.
 */

const MODE_CONFIG = {
  gaming: { label: 'Gaming', color: '#4a6cf7', icon: '🎮' },
  working: { label: 'Working', color: '#34d399', icon: '💻' },
  watching: { label: 'Watching', color: '#fbbf24', icon: '🎬' },
  social: { label: 'Party', color: '#f472b6', icon: '🎉' },
  relax: { label: 'Relax', color: '#a78bfa', icon: '🌙' },
  movie: { label: 'Movie', color: '#fbbf24', icon: '🍿' },
  sleeping: { label: 'Sleeping', color: '#6366f1', icon: '😴' },
  idle: { label: 'Idle', color: '#5c5e6a', icon: '💤' },
  away: { label: 'Away', color: '#5c5e6a', icon: '🚪' },
}

const SOCIAL_STYLE_LABELS = {
  color_cycle: 'Color Cycle',
  club: 'Club',
  rave: 'Rave',
  fire_and_ice: 'Fire & Ice',
}

import { memo } from 'react'

export const ModeIndicator = memo(function ModeIndicator({ mode, source, manualOverride, socialStyle }) {
  const config = MODE_CONFIG[mode] || MODE_CONFIG.idle
  const showSocialDetail = mode === 'social' && socialStyle

  return (
    <div className="mode-indicator">
      <span className="mode-icon">{config.icon}</span>
      <div className="mode-info">
        <span className="mode-label" style={{ color: config.color }}>
          {config.label}
          {showSocialDetail && (
            <span className="mode-sub-label">
              {' '}— {SOCIAL_STYLE_LABELS[socialStyle] || socialStyle}
            </span>
          )}
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
})
