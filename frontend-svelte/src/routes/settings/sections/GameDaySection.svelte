<script>
  import { Trophy } from 'lucide-svelte'
  import SettingsSection from '$lib/components/settings/SettingsSection.svelte'
  import GameDayTestGrid from '$lib/components/settings/GameDayTestGrid.svelte'
</script>

<SettingsSection
  title="Game Day"
  description="Smoke-test the celebration orchestrator without waiting for a real game. Tune SEQUENCES + TTS lines before preseason kicks off 2026-08-13."
  icon={Trophy}
>
  <GameDayTestGrid />
</SettingsSection>
