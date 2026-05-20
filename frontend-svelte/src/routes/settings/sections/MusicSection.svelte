<script>
  import { Music } from 'lucide-svelte'
  import SettingsSection from '$lib/components/settings/SettingsSection.svelte'
  import ModePlaylistMapper from '$lib/components/ModePlaylistMapper.svelte'
</script>

<SettingsSection
  title="Music"
  description="Map each mode to a Sonos favorite. Optional vibe tags (energetic / mellow / hype) feed the music bandit's context-aware picks."
  icon={Music}
  flush
>
  <ModePlaylistMapper />
</SettingsSection>
