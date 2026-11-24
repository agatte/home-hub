<script>
  import { lights } from '$lib/stores/lights.js'
  import { connected, deviceStatus } from '$lib/stores/connection.js'
  import { lightCommandResults } from '$lib/stores/lightCommandResults.js'
  import { setLight } from '$lib/stores/init.js'
  import LightCard from './LightCard.svelte'

  /** Existing HomeHub fixture IDs, not a new actuation authority. */
  export let room
  export let id
  export let compact = false

  // Each card sends one existing light_command over HomeHub's WebSocket.
  // Individual cards remain independent. Only the explicit Kitchen pair
  // power buttons below send to the two configured fixtures.
  const ROOM_LIGHTS = Object.freeze({
    living: ['1'],
    bedroom: ['2', '5'],
    kitchen: ['3', '4'],
    plant: ['6'],
  })
  const ROOMS = Object.freeze({
    living: 'Living',
    bedroom: 'Bedroom',
    kitchen: 'Kitchen',
    plant: 'Plant',
  })
  $: fixtureIds = ROOM_LIGHTS[room] ?? []
  $: roomLabel = ROOMS[room] ?? 'Room'
  const KITCHEN_IDS = ROOM_LIGHTS.kitchen
  $: kitchenReady = room === 'kitchen' && $connected && $deviceStatus.light_command_results === true && KITCHEN_IDS.every(lid => $lights[lid]?.reachable === true)
  $: kitchenPending = KITCHEN_IDS.some(lid => $lightCommandResults[lid]?.status === 'pending')
  $: kitchenOnCount = KITCHEN_IDS.filter(lid => $lights[lid]?.on === true).length

  /** @param {boolean} on */
  function setKitchenPower(on) {
    if (room !== 'kitchen' || !kitchenReady || kitchenPending) return
    // Each target retains its own authorization, receipt, and state readback.
    // This is not an atomic Hue group write, and partial success is possible.
    for (const lid of KITCHEN_IDS) setLight(lid, { on })
  }
</script>

<section class="room-control" class:compact aria-labelledby={`${id}-heading`}>
  <h4 id={`${id}-heading`} class="sr-only">Individual {roomLabel} lights</h4>
  {#if !$connected}
    <p role="status" class="warning">Lighting commands are unavailable while HomeHub is disconnected. Reconnect before adjusting.</p>
  {:else if $deviceStatus.light_command_results !== true}
    <p role="status" class="warning">This HomeHub server does not yet support guarded lighting command results. These redesigned controls will stay unavailable until the matching server update. The original Apartment controls remain accessible below.</p>
  {:else if fixtureIds.length === 0}
    <p role="status" class="warning">No configured fixtures for this room.</p>
  {:else}
    {#if room === 'kitchen'}
      <div class="kitchen-power" aria-busy={kitchenPending}>
        <div class="kitchen-summary"><strong>Both kitchen lights</strong><span>{!kitchenReady ? 'Waiting for both lights' : kitchenPending ? 'Changing lights…' : kitchenOnCount === 2 ? 'Both on' : kitchenOnCount === 0 ? 'Both off' : '1 of 2 on'}</span></div>
        <div class="kitchen-actions">
          <button type="button" disabled={!kitchenReady || kitchenPending} on:click={() => setKitchenPower(true)}>Both on</button>
          <button type="button" disabled={!kitchenReady || kitchenPending} on:click={() => setKitchenPower(false)}>Both off</button>
        </div>
      </div>
    {/if}
    {#if compact}<p class="light-hint">Drag to dim · tap power or color</p>{/if}
    <div class="fixture-grid">
      {#each fixtureIds as lightId (lightId)}
        <div class="fixture" class:identified={$lights[lightId]?.reachable === true} aria-label={`Light L${lightId}`}>
          <div class="fixture-heading"><span class="fixture-id">L{lightId}</span></div>
          {#if $lights[lightId] && $lights[lightId].reachable === true}
            <LightCard light={$lights[lightId]} optimisticStore={false} />
          {:else}
            <p role="status" class="warning">{ $lights[lightId] ? 'Fixture unreachable — controls unavailable' : 'Waiting for fixture state — controls unavailable' }</p>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
  <details class="control-details">
    <summary>About these controls</summary>
    <p class="provenance">Each slider requests a change to one light. Kitchen pair power sends one request to each kitchen light; either may be refused independently. HomeHub can refuse a change when another mode or effect is in control. Opening a room does not change any lights.</p>
    <p class="footnote">A successful request does not guarantee the physical light changed. Check the light itself when needed.</p>
    <a href="/classic#apartment-controls">Classic light controls</a>
  </details>
</section>

<style>
  .room-control {grid-column:1 / -1;min-width:0;}
  .sr-only {position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;border:0;}
  .provenance,.footnote { font-size:13px;line-height:1.6;color:var(--muted);max-width:70ch; }
  .kitchen-power {display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px;padding:12px;border:1px solid var(--line);border-radius:14px;margin:0 0 10px;}
  .kitchen-summary {display:grid;gap:4px;flex:1 1 130px;min-width:0;}
  .kitchen-summary strong {font-size:14px;color:var(--ink);}
  .kitchen-summary span {font-size:12px;color:var(--muted);}
  .kitchen-actions {display:flex;gap:6px;flex-wrap:wrap;}
  .kitchen-actions button {min-height:44px;padding:8px 12px;border:1px solid var(--line);border-radius:10px;background:rgba(237,207,160,.08);font:inherit;font-size:13px;color:var(--ink);cursor:pointer;}
  .kitchen-actions button:disabled {opacity:.5;cursor:not-allowed;}
  .kitchen-actions button:focus-visible {outline:3px solid var(--gold);outline-offset:2px;}
  .fixture-grid {display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:12px;min-width:0;margin:12px 0 16px;}
  .fixture {min-width:0;padding:0;border:0;}
  .fixture-heading {display:flex;align-items:center;min-height:25px;margin:0 0 5px;}
  .fixture-id {display:inline-flex;align-items:center;font-size:11px;font-weight:750;letter-spacing:.1em;color:var(--gold);}
  .warning { font-size:14px; line-height:1.5; padding:14px; border:1px solid var(--line);border-radius:8px; }
  .control-details {margin-top:10px;color:var(--muted);font-size:13px;}
  .light-hint {font-size:12px;color:var(--muted);line-height:1.4;margin:0 0 9px;}
  .compact .fixture-grid {gap:9px;margin:0;}
  .compact .fixture.identified .fixture-heading {position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);min-height:0;margin:0;}
  .compact .control-details {margin-top:3px;}
  .compact :global(.light-chip) {border-radius:13px;}
  .control-details summary {display:flex;align-items:center;min-height:44px;cursor:pointer;}
  a {display:inline-flex;align-items:center;min-height:44px;font-size:14px;color:var(--gold);text-decoration:underline;text-underline-offset:4px; }
  a:focus-visible {outline:3px solid var(--gold);outline-offset:3px;}
  :global(.room-control .light-card-owner) {min-width:0;max-width:100%;}
  /* Keep LightCard's guarded behavior; make its surface read as a Home control rather than a Classic card. */
  :global(.room-control .light-chip) {min-height:82px;border-radius:17px;border:1px solid var(--line);padding:17px;background:linear-gradient(120deg,rgba(235,218,177,.06),rgba(255,255,255,.015));}
  :global(.room-control .light-chip.light-on) {border-color:rgba(237,207,160,.3);}
  :global(.room-control .chip-name) {font-family:inherit;font-size:16px;font-weight:650;color:var(--ink);}
  :global(.room-control .chip-pct) {font-size:13px;color:var(--muted);}
  :global(.room-control .chip-power) {width:44px;height:44px;border:1px solid var(--line);border-radius:13px;background:rgba(255,255,255,.06);color:var(--ink);}
  :global(.room-control .chip-power.power-on) {color:var(--gold);background:rgba(237,207,160,.12);}
  :global(.room-control .chip-command-status) {font-size:13px;color:var(--muted);}
  @media(max-width:700px) {
    :global(.room-control .light-chip) {min-height:78px;padding:13px;}
  }
  @media(max-width:700px) {.fixture-grid {grid-template-columns:minmax(0,1fr);}}
</style>
