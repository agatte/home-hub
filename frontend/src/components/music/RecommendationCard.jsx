import { memo, useState, useCallback } from 'react'

export const RecommendationCard = memo(function RecommendationCard({ rec, onFeedback, onPreview }) {
  const [previewing, setPreviewing] = useState(false)

  const handlePreview = useCallback(async () => {
    if (!rec.preview_url) return
    setPreviewing(true)
    await onPreview(rec.preview_url)
    // Preview plays for ~30s, but don't block the UI
    setTimeout(() => setPreviewing(false), 3000)
  }, [rec.preview_url, onPreview])

  return (
    <div className="rec-card">
      {rec.artwork_url ? (
        <img
          className="rec-artwork"
          src={rec.artwork_url}
          alt={rec.artist_name}
          loading="lazy"
        />
      ) : (
        <div className="rec-artwork rec-artwork-placeholder">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M8 17.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5Z" />
            <path d="M10.5 15V3.5L17 2v11" />
          </svg>
        </div>
      )}
      <div className="rec-info">
        <span className="rec-artist">{rec.artist_name}</span>
        {rec.track_name && (
          <span className="rec-track">{rec.track_name}</span>
        )}
        {rec.reason && (
          <span className="rec-reason">{rec.reason}</span>
        )}
      </div>
      <div className="rec-actions">
        {rec.preview_url && (
          <button
            className="rec-action-btn rec-preview-btn"
            onClick={handlePreview}
            disabled={previewing}
            title="Play 30s preview on Sonos"
          >
            <svg width="12" height="12" viewBox="0 0 20 20" fill="currentColor" stroke="none">
              <polygon points="6,4 18,10 6,16" />
            </svg>
          </button>
        )}
        <button
          className="rec-action-btn rec-like-btn"
          onClick={() => onFeedback(rec.id, 'liked')}
          title="Like"
        >
          <svg width="12" height="12" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="4,10 8,14 16,6" />
          </svg>
        </button>
        <button
          className="rec-action-btn rec-dismiss-btn"
          onClick={() => onFeedback(rec.id, 'dismissed')}
          title="Dismiss"
        >
          <svg width="12" height="12" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="5" y1="5" x2="15" y2="15" />
            <line x1="15" y1="5" x2="5" y2="15" />
          </svg>
        </button>
        {rec.itunes_url && (
          <a
            className="rec-action-btn rec-apple-btn"
            href={rec.itunes_url}
            target="_blank"
            rel="noopener noreferrer"
            title="Open in Apple Music"
          >
            <svg width="12" height="12" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 3l3 3-3 3" />
              <path d="M3 10V8a4 4 0 0 1 4-4h10" />
            </svg>
          </a>
        )}
      </div>
    </div>
  )
})
