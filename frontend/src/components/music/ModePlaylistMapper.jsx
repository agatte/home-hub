import { useState, useEffect, useCallback, memo } from 'react'

const MODE_CONFIG = [
  { mode: 'gaming', label: 'Gaming', icon: '\uD83C\uDFAE' },
  { mode: 'working', label: 'Working', icon: '\uD83D\uDCBB' },
  { mode: 'watching', label: 'Watching', icon: '\uD83C\uDFAC' },
  { mode: 'relax', label: 'Relax', icon: '\uD83D\uDECB\uFE0F' },
  { mode: 'social', label: 'Party', icon: '\uD83C\uDF89' },
  { mode: 'movie', label: 'Movie', icon: '\uD83C\uDF7F' },
]

export const ModePlaylistMapper = memo(function ModePlaylistMapper() {
  const [mappings, setMappings] = useState({})
  const [favorites, setFavorites] = useState([])
  const [saving, setSaving] = useState(null)

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch('/api/music/mode-playlists')
      const data = await res.json()
      setMappings(data.mappings || {})
      setFavorites(data.favorites || [])
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const handleFavoriteChange = useCallback(async (mode, title) => {
    const current = mappings[mode]
    const autoPlay = current?.auto_play || false

    if (!title) {
      // Remove mapping
      try {
        await fetch(`/api/music/mode-playlists/${mode}`, { method: 'DELETE' })
        setMappings(prev => ({ ...prev, [mode]: null }))
      } catch { /* ignore */ }
      return
    }

    setSaving(mode)
    try {
      await fetch(`/api/music/mode-playlists/${mode}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ favorite_title: title, auto_play: autoPlay }),
      })
      setMappings(prev => ({
        ...prev,
        [mode]: { mode, favorite_title: title, auto_play: autoPlay },
      }))
    } catch { /* ignore */ }
    setSaving(null)
  }, [mappings])

  const handleAutoPlayToggle = useCallback(async (mode) => {
    const current = mappings[mode]
    if (!current?.favorite_title) return

    const newAutoPlay = !current.auto_play
    setSaving(mode)
    try {
      await fetch(`/api/music/mode-playlists/${mode}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ favorite_title: current.favorite_title, auto_play: newAutoPlay }),
      })
      setMappings(prev => ({
        ...prev,
        [mode]: { ...current, auto_play: newAutoPlay },
      }))
    } catch { /* ignore */ }
    setSaving(null)
  }, [mappings])

  return (
    <div className="mode-playlist-mapper">
      {MODE_CONFIG.map(({ mode, label, icon }) => {
        const mapping = mappings[mode]
        const selectedTitle = mapping?.favorite_title || ''

        return (
          <div key={mode} className="mode-playlist-row">
            <div className="mode-playlist-mode">
              <span className="mode-playlist-icon">{icon}</span>
              <span className="mode-playlist-label">{label}</span>
            </div>
            <div className="mode-playlist-controls">
              <select
                className="setting-select mode-playlist-select"
                value={selectedTitle}
                onChange={(e) => handleFavoriteChange(mode, e.target.value)}
                disabled={saving === mode}
              >
                <option value="">None</option>
                {favorites.map((fav) => (
                  <option key={fav.title} value={fav.title}>
                    {fav.title}
                  </option>
                ))}
              </select>
              <button
                className={`toggle-btn ${mapping?.auto_play ? 'toggle-on' : ''}`}
                onClick={() => handleAutoPlayToggle(mode)}
                disabled={!selectedTitle || saving === mode}
                title={mapping?.auto_play ? 'Auto-play enabled' : 'Auto-play disabled'}
              >
                {mapping?.auto_play ? 'Auto' : 'Manual'}
              </button>
            </div>
          </div>
        )
      })}
      {favorites.length === 0 && (
        <p className="mode-playlist-hint">
          No Sonos favorites found. Add playlists in the Sonos app, then map them here.
        </p>
      )}
    </div>
  )
})
