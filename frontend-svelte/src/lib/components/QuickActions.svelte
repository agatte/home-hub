<script>
  import { automation } from '$lib/stores/automation.js'
  import { setManualMode } from '$lib/stores/init.js'
  import { apiPost } from '$lib/api.js'

  const ACTIONS = [
    { id: 'movie', label: 'Movie', mode: 'movie' },
    { id: 'relax', label: 'Relax', mode: 'relax' },
    { id: 'social', label: 'Party', mode: 'social' },
    { id: 'sleeping', label: 'Bedtime', mode: 'sleeping' },
    { id: 'auto', label: 'Auto', mode: 'auto' },
  ]

  $: currentMode = $automation.mode

  async function allOff() {
    try {
      await apiPost('/api/lights/all', { on: false })
    } catch {
      /* ignore */
    }
  }
</script>

<div class="quick-actions">
  <button class="quick-action quick-action-danger" on:click={allOff}>All off</button>
  {#each ACTIONS as action}
    <button
      class="quick-action"
      class:quick-action-active={currentMode === action.mode}
      on:click={() => setManualMode(action.mode)}
    >
      {action.label}
    </button>
  {/each}
</div>
