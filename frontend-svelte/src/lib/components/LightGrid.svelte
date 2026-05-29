<script>
  import { lights } from '$lib/stores/lights.js'
  import LightCard from './LightCard.svelte'

  // Kitchen pair (L3 front + L4 back) is fused into a single "Kitchen" card.
  // The two lights are ganged in every functional mode anyway (kitchen-pair
  // rule in CLAUDE.md), so independent control is just noise. We render L3
  // with linkedIds=['4'] so every command fans out to both lights, hide the
  // L4 card, and override the name to "Kitchen". Reachability rolls up:
  // either bulb offline → the fused card shows offline.
  //
  // L1 (living room), L2 (bedroom lamp left), L5 (bedroom lamp right, added
  // 2026-05-11) each render as their own card — no pair-fusion rule applies
  // outside the kitchen.
  //
  // Display order walks the apartment from back to front: bedroom right (L5),
  // bedroom left (L2), kitchen (L3+L4 fused), living room (L1).
  const DISPLAY_ORDER = ['5', '2', '3', '1']
  $: lightList = Object.values($lights)
    .filter((l) => l.light_id !== '4')
    .sort(
      (a, b) =>
        DISPLAY_ORDER.indexOf(a.light_id) - DISPLAY_ORDER.indexOf(b.light_id),
    )

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
