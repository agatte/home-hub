import { TasteProfileCard } from '../components/music/TasteProfileCard'
import { ModePlaylistMapper } from '../components/music/ModePlaylistMapper'
import { RecommendationPanel } from '../components/music/RecommendationPanel'

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

      <section className="section">
        <h2 className="section-title">Discover</h2>
        <p className="music-description">
          Recommendations based on your taste profile. Preview tracks on Sonos,
          like to improve future suggestions, or open in Apple Music to add to your library.
        </p>
        <RecommendationPanel />
      </section>
    </main>
  )
}
