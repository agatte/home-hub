<script>
  import { Brain } from 'lucide-svelte'
  import SettingsSection from '$lib/components/settings/SettingsSection.svelte'
  import LearnedRulesCard from '$lib/components/LearnedRulesCard.svelte'
  import RuleSuggestionHistoryCard from '$lib/components/RuleSuggestionHistoryCard.svelte'
</script>

<SettingsSection
  title="Learning"
  description="Rules the engine has learned from your overrides, plus the audit log of every suggestion fired."
  icon={Brain}
  flush
>
  <div class="learning-stack">
    <LearnedRulesCard />
    <RuleSuggestionHistoryCard />
  </div>
</SettingsSection>

<style>
  .learning-stack {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
</style>
