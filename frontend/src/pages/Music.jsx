import { TasteProfileCard } from '../components/music/TasteProfileCard'
import { ModePlaylistMapper } from '../components/music/ModePlaylistMapper'

export function Music() {
  return (
    <main className="home-page">
      <section className="section">
        <h2 className="section-title">Taste Profile</h2>
        <TasteProfileCard />
      </section>

      <section className="section">
        <h2 className="section-title">Mode Playlists</h2>
        <p className="music-description">
          Map Sonos favorites to activity modes. When a mode activates, the mapped playlist
          auto-plays if Sonos is idle, or you'll get a suggestion to switch.
        </p>
        <ModePlaylistMapper />
      </section>
    </main>
  )
}
