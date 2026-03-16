import { memo } from 'react'
import { useMusic } from '../../context/HubContext'

const MODE_LABELS = {
  gaming: 'Gaming',
  working: 'Working',
  watching: 'Watching',
  relax: 'Relax',
  social: 'Party',
  movie: 'Movie',
}

export const MusicSuggestionToast = memo(function MusicSuggestionToast() {
  const { musicSuggestion, musicAutoPlayed, dismissMusicSuggestion, acceptMusicSuggestion } = useMusic()

  if (!musicSuggestion && !musicAutoPlayed) return null

  // Auto-played toast (brief confirmation)
  if (musicAutoPlayed && !musicSuggestion) {
    return (
      <div className="music-toast music-toast-info">
        <span className="music-toast-icon">
          <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M8 17.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5Z" />
            <path d="M10.5 15V3.5L17 2v11" />
            <path d="M17 13a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0Z" />
          </svg>
        </span>
        <span className="music-toast-text">
          Now playing <strong>{musicAutoPlayed.title}</strong> for {MODE_LABELS[musicAutoPlayed.mode] || musicAutoPlayed.mode}
        </span>
      </div>
    )
  }

  // Suggestion toast (interactive)
  if (musicSuggestion) {
    return (
      <div className="music-toast music-toast-suggestion">
        <div className="music-toast-content">
          <span className="music-toast-icon">
            <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M8 17.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5Z" />
              <path d="M10.5 15V3.5L17 2v11" />
              <path d="M17 13a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0Z" />
            </svg>
          </span>
          <span className="music-toast-text">
            {MODE_LABELS[musicSuggestion.mode] || musicSuggestion.mode} mode — play <strong>{musicSuggestion.title}</strong>?
          </span>
        </div>
        <div className="music-toast-actions">
          <button className="music-toast-btn music-toast-accept" onClick={acceptMusicSuggestion}>
            <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polygon points="6,4 18,10 6,16" fill="currentColor" stroke="none" />
            </svg>
            Play
          </button>
          <button className="music-toast-btn music-toast-dismiss" onClick={dismissMusicSuggestion}>
            <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="5" y1="5" x2="15" y2="15" />
              <line x1="15" y1="5" x2="5" y2="15" />
            </svg>
          </button>
        </div>
        <div className="music-toast-progress" />
      </div>
    )
  }

  return null
})
