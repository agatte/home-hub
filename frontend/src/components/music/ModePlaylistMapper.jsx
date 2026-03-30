import { useState, useEffect, useCallback, memo, useRef } from 'react'

const MODE_CONFIG = [
  { mode: 'gaming', label: 'Gaming', icon: '\uD83C\uDFAE' },
  { mode: 'working', label: 'Working', icon: '\uD83D\uDCBB' },
  { mode: 'watching', label: 'Watching', icon: '\uD83C\uDFAC' },
  { mode: 'relax', label: 'Relax', icon: '\uD83D\uDECB\uFE0F' },
  { mode: 'social', label: 'Party', icon: '\uD83C\uDF89' },
  { mode: 'movie', label: 'Movie', icon: '\uD83C\uDF7F' },
]

const VIBES = [
  { value: '', label: 'No vibe tag' },
  { value: 'energetic', label: '\u26A1 Energetic' },
  { value: 'focus', label: '\uD83C\uDFAF Focus' },
  { value: 'mellow', label: '\uD83C\uDF19 Mellow' },
  { value: 'background', label: '\uD83C\uDFA7 Background' },
  { value: 'hype', label: '\uD83D\uDD25 Hype' },
]

function AddMappingRow({ mode, favorites, onAdd }) {
  const [title, setTitle] = useState('')
  const [vibe, setVibe] = useState('')
  const [autoPlay, setAutoPlay] = useState(false)
  const [saving, setSaving] = useState(false)

  const handleAdd = async () => {
    if (!title) return
    setSaving(true)
    await onAdd({ mode, favorite_title: title, vibe: vibe || null, auto_play: autoPlay })
    setTitle('')
    setVibe('')
    setAutoPlay(false)
    setSaving(false)
  }

  return (
    <div className="mode-playlist-add-row">
      <select
        className="setting-select mode-playlist-select"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      >
        <option value="">Add favorite…</option>
        {favorites.map((fav) => (
          <option key={fav.title} value={fav.title}>{fav.title}</option>
        ))}
      </select>
      <select
        className="setting-select vibe-select"
        value={vibe}
        onChange={(e) => setVibe(e.target.value)}
        disabled={!title}
      >
        {VIBES.map((v) => (
          <option key={v.value} value={v.value}>{v.label}</option>
        ))}
      </select>
      <button
        className={`toggle-btn ${autoPlay ? 'toggle-on' : ''}`}
        onClick={() => setAutoPlay((p) => !p)}
        disabled={!title}
        title={autoPlay ? 'Auto-play on mode change' : 'Manual play only'}
      >
        {autoPlay ? 'Auto' : 'Manual'}
      </button>
      <button
        className="icon-btn add-btn"
        onClick={handleAdd}
        disabled={!title || saving}
        title="Add mapping"
      >
        +
      </button>
    </div>
  )
}

function MappingEntry({ entry, onRemove }) {
  const vibe = VIBES.find((v) => v.value === (entry.vibe || ''))
  return (
    <div className="mode-playlist-entry">
      <span className="entry-title">{entry.favorite_title}</span>
      {entry.vibe && (
        <span className="entry-vibe">{vibe?.label || entry.vibe}</span>
      )}
      <span className={`entry-auto ${entry.auto_play ? 'auto-on' : 'auto-off'}`}>
        {entry.auto_play ? 'Auto' : 'Manual'}
      </span>
      <button
        className="icon-btn remove-btn"
        onClick={() => onRemove(entry.id)}
        title="Remove"
      >
        ×
      </button>
    </div>
  )
}

export const ModePlaylistMapper = memo(function ModePlaylistMapper() {
  const [mappings, setMappings] = useState({})
  const [favorites, setFavorites] = useState([])
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    fetch('/api/music/mode-playlists')
      .then((r) => r.json())
      .then((data) => {
        if (mountedRef.current) {
          setMappings(data.mappings || {})
          setFavorites(data.favorites || [])
        }
      })
      .catch(() => {})
    return () => { mountedRef.current = false }
  }, [])

  const handleAdd = useCallback(async (body) => {
    try {
      const res = await fetch('/api/music/mode-playlists', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) return
      const data = await res.json()
      // Add the new entry to local state immediately
      setMappings((prev) => ({
        ...prev,
        [body.mode]: [
          ...(prev[body.mode] || []),
          {
            id: data.id,
            mode: body.mode,
            favorite_title: body.favorite_title,
            vibe: body.vibe || null,
            auto_play: body.auto_play,
            priority: body.priority || 0,
          },
        ],
      }))
    } catch { /* ignore */ }
  }, [])

  const handleRemove = useCallback(async (mode, mappingId) => {
    try {
      await fetch(`/api/music/mode-playlists/${mappingId}`, { method: 'DELETE' })
      setMappings((prev) => ({
        ...prev,
        [mode]: (prev[mode] || []).filter((e) => e.id !== mappingId),
      }))
    } catch { /* ignore */ }
  }, [])

  return (
    <div className="mode-playlist-mapper">
      {MODE_CONFIG.map(({ mode, label, icon }) => {
        const entries = mappings[mode] || []
        return (
          <div key={mode} className="mode-playlist-row">
            <div className="mode-playlist-mode">
              <span className="mode-playlist-icon">{icon}</span>
              <span className="mode-playlist-label">{label}</span>
            </div>
            <div className="mode-playlist-entries">
              {entries.map((entry) => (
                <MappingEntry
                  key={entry.id}
                  entry={entry}
                  onRemove={(id) => handleRemove(mode, id)}
                />
              ))}
              {favorites.length > 0 && (
                <AddMappingRow
                  mode={mode}
                  favorites={favorites}
                  onAdd={handleAdd}
                />
              )}
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
