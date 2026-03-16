import { memo } from 'react'
import { StatusDot } from '../common/StatusDot'

export const Header = memo(function Header({ connected, deviceStatus, page, onPageChange }) {
  return (
    <header className="app-header">
      <h1
        className="app-title"
        onClick={() => onPageChange('home')}
        style={{ cursor: 'pointer' }}
      >
        Home Hub
      </h1>
      <div className="header-right">
        <div className="status-bar">
          <StatusDot active={connected} label="Server" />
          <StatusDot active={deviceStatus.hue} label="Hue" />
          <StatusDot active={deviceStatus.sonos} label="Sonos" />
        </div>
        <button
          className={`settings-btn ${page === 'music' ? 'settings-btn-active' : ''}`}
          onClick={() => onPageChange(page === 'music' ? 'home' : 'music')}
          aria-label="Music"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M8 17.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5Z" />
            <path d="M10.5 15V3.5L17 2v11" />
            <path d="M17 13a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0Z" />
          </svg>
        </button>
        <button
          className={`settings-btn ${page === 'settings' ? 'settings-btn-active' : ''}`}
          onClick={() => onPageChange(page === 'settings' ? 'home' : 'settings')}
          aria-label="Settings"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="10" cy="10" r="3" />
            <path d="M10 1.5v2M10 16.5v2M1.5 10h2M16.5 10h2M3.4 3.4l1.4 1.4M15.2 15.2l1.4 1.4M3.4 16.6l1.4-1.4M15.2 4.8l1.4-1.4" />
          </svg>
        </button>
      </div>
    </header>
  )
})
