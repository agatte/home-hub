<script>
  import { Volume2 } from 'lucide-svelte'
  import SettingsSection from '$lib/components/settings/SettingsSection.svelte'
  import AmbientSettings from '$lib/components/AmbientSettings.svelte'
</script>

<SettingsSection
  title="Audio"
  description="Browser ambient sound + Sonos mirroring. Per-mode sound selection with day/evening/night volume curves."
  icon={Volume2}
  flush
>
  <AmbientSettings />
</SettingsSection>
