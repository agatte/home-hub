import { useState, useEffect, useCallback, memo, useRef } from 'react'
import { GenreDonut } from './GenreDonut'

export const TasteProfileCard = memo(function TasteProfileCard() {
  const [profile, setProfile] = useState(null)
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState(null)
  const fileRef = useRef(null)

  const fetchProfile = useCallback(async () => {
    try {
      const res = await fetch('/api/music/profile')
      const data = await res.json()
      if (data.profile) setProfile(data.profile)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { fetchProfile() }, [fetchProfile])

  const handleImport = useCallback(async (e) => {
    const file = e.target.files?.[0]
    if (!file) return

    setImporting(true)
    setImportResult(null)

    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await fetch('/api/music/import', {
        method: 'POST',
        body: formData,
      })
      if (!res.ok) {
        const err = await res.json()
        setImportResult({ error: err.detail || 'Import failed' })
      } else {
        const data = await res.json()
        setImportResult(data)
        // Refresh profile
        await fetchProfile()
      }
    } catch (err) {
      setImportResult({ error: 'Network error during import' })
    }

    setImporting(false)
    // Reset file input so re-uploading the same file works
    if (fileRef.current) fileRef.current.value = ''
  }, [fetchProfile])

  // No profile yet — show import prompt
  if (!profile) {
    return (
      <div className="taste-profile-card">
        <div className="taste-profile-empty">
          <div className="taste-profile-empty-icon">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
          </div>
          <p className="taste-profile-empty-text">
            Import your Apple Music library to build a taste profile
          </p>
          <p className="taste-profile-empty-hint">
            In iTunes: File &gt; Library &gt; Export Library
          </p>
          <label className={`action-btn taste-profile-import-btn ${importing ? 'importing' : ''}`}>
            {importing ? 'Importing...' : 'Import Library XML'}
            <input
              ref={fileRef}
              type="file"
              accept=".xml"
              onChange={handleImport}
              disabled={importing}
              hidden
            />
          </label>
          {importResult?.error && (
            <p className="taste-profile-error">{importResult.error}</p>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="taste-profile-card">
      <div className="taste-profile-header">
        <div className="taste-profile-stats">
          <div className="taste-profile-stat">
            <span className="taste-profile-stat-value">{profile.import_track_count.toLocaleString()}</span>
            <span className="taste-profile-stat-label">tracks</span>
          </div>
          <div className="taste-profile-stat">
            <span className="taste-profile-stat-value">{profile.import_artist_count.toLocaleString()}</span>
            <span className="taste-profile-stat-label">artists</span>
          </div>
          <div className="taste-profile-stat">
            <span className="taste-profile-stat-value">{Object.keys(profile.genre_distribution).length}</span>
            <span className="taste-profile-stat-label">genres</span>
          </div>
        </div>
        <label className={`action-btn taste-profile-reimport ${importing ? 'importing' : ''}`}>
          {importing ? 'Importing...' : 'Re-import'}
          <input
            ref={fileRef}
            type="file"
            accept=".xml"
            onChange={handleImport}
            disabled={importing}
            hidden
          />
        </label>
      </div>

      <GenreDonut distribution={profile.genre_distribution} />

      {profile.top_artists && profile.top_artists.length > 0 && (
        <div className="taste-profile-top-artists">
          <h4 className="subsection-title">Top Artists</h4>
          <div className="top-artists-list">
            {profile.top_artists.slice(0, 8).map((artist, i) => (
              <div key={artist.name} className="top-artist-row">
                <span className="top-artist-rank">{i + 1}</span>
                <span className="top-artist-name">{artist.name}</span>
                <span className="top-artist-plays">{artist.play_count} plays</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {importResult && !importResult.error && (
        <p className="taste-profile-success">
          Imported {importResult.track_count} tracks from {importResult.artist_count} artists
        </p>
      )}
      {importResult?.error && (
        <p className="taste-profile-error">{importResult.error}</p>
      )}
    </div>
  )
})
