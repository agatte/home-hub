<script>
  import { lights } from '$lib/stores/lights.js'
  import LightCard from './LightCard.svelte'

  // Kitchen pair (L3 front + L4 back) is fused into a single "Kitchen" card.
  // The two lights are ganged in every functional mode anyway (kitchen-pair
  // rule in CLAUDE.md), so independent control is just noise. We render L3
  // with linkedIds=['4'] so every command fans out to both lights, hide the
  // L4 card, and override the name to "Kitchen". Reachability rolls up:
  // either bulb offline → the fused card shows offline.
  $: lightList = Object.values($lights)
    .filter((l) => l.light_id !== '4')
    .sort((a, b) => Number(a.light_id) - Number(b.light_id))

  $: l4 = $lights['4']
</script>

{#if lightList.length === 0}
  <div class="empty-state">No lights found</div>
{:else}
  <div class="light-grid">
    {#each lightList as light (light.light_id)}
      {#if light.light_id === '3'}
        <LightCard
          light={l4 ? { ...light, reachable: light.reachable && l4.reachable } : light}
          linkedIds={['4']}
          nameOverride="Kitchen"
        />
      {:else}
        <LightCard {light} />
      {/if}
    {/each}
  </div>
{/if}
