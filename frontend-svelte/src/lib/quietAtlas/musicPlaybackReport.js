/** Validate the existing Sonos status response without inventing a track or playback state. */
export function musicPlaybackReport(value) {
  if (!value || !['PLAYING','PAUSED_PLAYBACK','STOPPED','TRANSITIONING','NO_MEDIA_PRESENT'].includes(value.state) ||
      !Number.isFinite(value.volume) || value.volume < 0 || value.volume > 100 ||
      typeof value.track !== 'string' || typeof value.artist !== 'string' || typeof value.album !== 'string') return null
  const art = typeof value.art_url === 'string' && /^(https?:\\/\\/|\\/(?!\\/))/.test(value.art_url) ? value.art_url : ''
  return {state:value.state,track:value.track,artist:value.artist,album:value.album,art_url:art,volume:value.volume}
}

/** Receipt age, not a guarantee of physical playback. */
export function recentPlaybackReport(report, receivedAt, now, available) {
  return available && report && receivedAt !== null && now >= receivedAt && now - receivedAt <= 30000 ? report : null
}
