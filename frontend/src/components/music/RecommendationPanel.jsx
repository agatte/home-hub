import { useState, useEffect, useCallback, memo } from 'react'
import { RecommendationCard } from './RecommendationCard'

const MODES = [
  { key: 'gaming', label: 'Gaming' },
  { key: 'working', label: 'Working' },
  { key: 'relax', label: 'Relax' },
  { key: 'social', label: 'Party' },
]

export const RecommendationPanel = memo(function RecommendationPanel() {
  const [activeMode, setActiveMode] = useState('gaming')
  const [recs, setRecs] = useState([])
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState(null)

  const fetchRecs = useCallback(async (mode) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`/api/music/recommendations?mode=${mode}`)
      const data = await res.json()
      setRecs(data.recommendations || [])
      if (data.message) setError(data.message)
    } catch {
      setError('Failed to fetch recommendations')
    }
    setLoading(false)
  }, [])

  useEffect(() => { fetchRecs(activeMode) }, [activeMode, fetchRecs])

  const handleGenerate = useCallback(async () => {
    setGenerating(true)
    setError(null)
    try {
      const res = await fetch(`/api/music/recommendations/generate?mode=${activeMode}`, {
        method: 'POST',
      })
      if (!res.ok) {
        const data = await res.json()
        setError(data.detail || 'Generation failed')
      } else {
        await fetchRecs(activeMode)
      }
    } catch {
      setError('Failed to generate recommendations')
    }
    setGenerating(false)
  }, [activeMode, fetchRecs])

  const handleFeedback = useCallback(async (recId, action) => {
    try {
      await fetch(`/api/music/recommendations/${recId}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      })
      // Remove from list optimistically
      setRecs(prev => prev.filter(r => r.id !== recId))
    } catch { /* ignore */ }
  }, [])

  const handlePreview = useCallback(async (previewUrl) => {
    try {
      await fetch('/api/music/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ preview_url: previewUrl }),
      })
    } catch { /* ignore */ }
  }, [])

  return (
    <div className="rec-panel">
      <div className="rec-tabs">
        {MODES.map(({ key, label }) => (
          <button
            key={key}
            className={`rec-tab ${activeMode === key ? 'rec-tab-active' : ''}`}
            onClick={() => setActiveMode(key)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="rec-content">
        {loading ? (
          <p className="rec-loading">Loading...</p>
        ) : recs.length > 0 ? (
          <div className="rec-list">
            {recs.map((rec) => (
              <RecommendationCard
                key={rec.id}
                rec={rec}
                onFeedback={handleFeedback}
                onPreview={handlePreview}
              />
            ))}
          </div>
        ) : (
          <div className="rec-empty">
            <p>{error || 'No recommendations yet for this mode.'}</p>
          </div>
        )}

        <button
          className="action-btn rec-generate-btn"
          onClick={handleGenerate}
          disabled={generating}
        >
          {generating ? 'Generating...' : 'Generate Recommendations'}
        </button>
      </div>
    </div>
  )
})
