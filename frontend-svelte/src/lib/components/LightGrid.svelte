<script>
  import { lights } from '$lib/stores/lights.js'
  import LightCard from './LightCard.svelte'

  $: lightList = Object.values($lights).sort(
    (a, b) => Number(a.light_id) - Number(b.light_id)
  )
</script>

{#if lightList.length === 0}
  <div class="empty-state">No lights found</div>
{:else}
  <div class="light-grid">
    {#each lightList as light (light.light_id)}
      <LightCard {light} />
    {/each}
  </div>
{/if}
