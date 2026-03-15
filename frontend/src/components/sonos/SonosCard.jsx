import { Slider } from '../common/Slider'

export function SonosCard({ sonos, onCommand }) {
  const isPlaying = sonos.state === 'PLAYING'

  return (
    <div className="sonos-card">
      <div className="now-playing">
        {sonos.art_url ? (
          <img src={sonos.art_url} alt="Album art" className="album-art" />
        ) : (
          <div className="album-art album-art-placeholder">
            <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M9 18V5l12-2v13" />
              <circle cx="6" cy="18" r="3" />
              <circle cx="18" cy="16" r="3" />
            </svg>
          </div>
        )}
        <div className="track-info">
          <div className="track-name">{sonos.track || 'Nothing playing'}</div>
          <div className="track-artist">{sonos.artist || '\u00A0'}</div>
          {sonos.album && <div className="track-album">{sonos.album}</div>}
        </div>
      </div>

      <div className="playback-controls">
        <button
          className="control-btn"
          onClick={() => onCommand('previous')}
          aria-label="Previous"
        >
          <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
            <path d="M6 6h2v12H6zm3.5 6l8.5 6V6z" />
          </svg>
        </button>

        <button
          className="control-btn control-btn-primary"
          onClick={() => onCommand(isPlaying ? 'pause' : 'play')}
          aria-label={isPlaying ? 'Pause' : 'Play'}
        >
          {isPlaying ? (
            <svg viewBox="0 0 24 24" width="28" height="28" fill="currentColor">
              <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" width="28" height="28" fill="currentColor">
              <path d="M8 5v14l11-7z" />
            </svg>
          )}
        </button>

        <button
          className="control-btn"
          onClick={() => onCommand('next')}
          aria-label="Next"
        >
          <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
            <path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" />
          </svg>
        </button>
      </div>

      <div className="volume-control">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" className="volume-icon">
          <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z" />
        </svg>
        <Slider
          value={sonos.volume}
          min={0}
          max={100}
          onChange={(vol) => onCommand('volume', { volume: vol })}
          className="volume-slider"
        />
      </div>
    </div>
  )
}
