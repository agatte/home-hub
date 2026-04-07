import { memo } from 'react'

const NAV_ITEMS = [
  {
    id: 'home',
    label: 'Home',
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 8.5L10 3l7 5.5V17a1 1 0 0 1-1 1h-3v-6H7v6H4a1 1 0 0 1-1-1V8.5Z" />
      </svg>
    ),
  },
  {
    id: 'music',
    label: 'Music',
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M8 17.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5Z" />
        <path d="M10.5 15V3.5L17 2v11" />
        <path d="M17 13a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0Z" />
      </svg>
    ),
  },
  {
    id: 'settings',
    label: 'Settings',
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="10" cy="10" r="3" />
        <path d="M10 1.5v2M10 16.5v2M1.5 10h2M16.5 10h2M3.4 3.4l1.4 1.4M15.2 15.2l1.4 1.4M3.4 16.6l1.4-1.4M15.2 4.8l1.4-1.4" />
      </svg>
    ),
  },
]

export const Sidebar = memo(function Sidebar({ page, onPageChange, mode, sonos }) {
  const playing = sonos?.state === 'PLAYING'
  const track = sonos?.track || 'Nothing playing'
  const artist = sonos?.artist || ''

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">Home Hub</div>
      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            className={`sidebar-nav-item ${page === item.id ? 'sidebar-nav-item-active' : ''}`}
            onClick={() => onPageChange(item.id)}
          >
            <span className="sidebar-nav-icon">{item.icon}</span>
            <span className="sidebar-nav-label">{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="sidebar-now-playing">
        <div className="sidebar-now-playing-label">
          {mode ? `Mode · ${mode}` : 'Mode'}
        </div>
        <div className={`sidebar-now-playing-track ${playing ? 'is-playing' : ''}`}>
          {track}
        </div>
        {artist && <div className="sidebar-now-playing-artist">{artist}</div>}
      </div>
    </aside>
  )
})
