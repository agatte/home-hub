<script>
  import { get } from 'svelte/store'
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
  // Individual cards remain independent. Only explicitly selected Kitchen
  // pair actions send to the two configured fixtures.
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
  let kitchenView = 'together'
  $: kitchenReady = room === 'kitchen' && $connected && $deviceStatus.light_command_results === true && KITCHEN_IDS.every(lid => $lights[lid]?.light_id === lid && $lights[lid]?.reachable === true && typeof $lights[lid]?.on === 'boolean')
  $: kitchenPending = KITCHEN_IDS.some(lid => $lightCommandResults[lid]?.status === 'pending')
  $: kitchenOnCount = KITCHEN_IDS.filter(lid => $lights[lid]?.on === true).length

  // Recheck current stores at the moment of an explicit action, not only
  // the last rendered state. No new room/group write endpoint.
  function pairCanWrite() {
    const current = get(lights)
    const receipts = get(lightCommandResults)
    return room === 'kitchen' && kitchenView === 'together' && get(connected) &&
      get(deviceStatus).light_command_results === true &&
      KITCHEN_IDS.every(lid => current[lid]?.light_id === lid && current[lid]?.reachable === true &&
        typeof current[lid]?.on === 'boolean' && receipts[lid]?.status !== 'pending')
  }

  function linkedCanWrite() {
    const current = get(lights)
    return pairCanWrite() && current['3']?.on === current['4']?.on
  }

  /** @param {string | undefined} status */
  function receiptLabel(status) {
    if (status === 'pending') return 'Changing light…'
    if (status === 'denied') return 'Light change blocked. Try again when available.'
    if (status === 'unavailable') return 'Control unavailable; no command sent.'
    if (status === 'invalid') return 'Request rejected.'
    return 'Result uncertain; check actual light.'
  }

  /** @param {boolean} on */
  function setKitchenPower(on) {
    if (!pairCanWrite()) return
    // Each target retains its own authorization, receipt, and state readback.
    // This is not an atomic Hue group write, and partial success is possible.
    for (const lid of KITCHEN_IDS) setLight(lid, { on })
  }
</script>

<section class="room-control" class:compact aria-labelledby={`${id}-heading`}>
  <h4 id={`${id}-heading`} class="sr-only">{roomLabel} lights</h4>
  {#if !$connected}
    <p role="status" class="warning">HomeHub is disconnected. Reconnect to adjust your lights.</p>
  {:else if $deviceStatus.light_command_results !== true}
    <p role="status" class="warning">Lighting controls are unavailable until HomeHub is updated.</p>
  {:else if fixtureIds.length === 0}
    <p role="status" class="warning">No lights configured for this room.</p>
  {:else}
    {#if room === 'kitchen'}
      <div class="kitchen-switch" role="group" aria-label="Kitchen control scope">
        <button type="button" aria-pressed={kitchenView === 'together'} on:click={() => kitchenView = 'together'}>Together</button>
        <button type="button" aria-pressed={kitchenView === 'individual'} on:click={() => kitchenView = 'individual'}>Individually</button>
      </div>
    {/if}
    {#if room === 'kitchen' && kitchenView === 'together'}
      <div class="kitchen-power" aria-busy={kitchenPending}>
        <div class="kitchen-summary"><strong>Both kitchen lights</strong><span>{!kitchenReady ? 'Waiting for both lights' : kitchenPending ? 'Changing lights…' : kitchenOnCount === 2 ? 'Both on' : kitchenOnCount === 0 ? 'Both off' : '1 of 2 on'}</span></div>
        <div class="kitchen-actions">
          <button type="button" disabled={!kitchenReady || kitchenPending} on:click={() => setKitchenPower(true)}>Both on</button>
          <button type="button" disabled={!kitchenReady || kitchenPending} on:click={() => setKitchenPower(false)}>Both off</button>
        </div>
      </div>
      {#if kitchenReady && kitchenOnCount !== 1}
        <p class="light-hint">Both lights receive each adjustment. Displayed brightness and color reference Kitchen front (L3); Kitchen back (L4) may differ.</p>
        <LightCard light={$lights['3']} linkedIds={['4']} nameOverride="Kitchen · front reference" writeAllowed={linkedCanWrite} />
      {:else}
        <p class="light-hint">{kitchenReady ? 'Power differs. Turn both on or off before linked brightness and color adjustments.' : 'Both fixtures must be reachable for linked adjustments. Use Individually to control an available light.'}</p>
        {#each KITCHEN_IDS as lid}
          {#if $lightCommandResults[lid]?.status && $lightCommandResults[lid].status !== 'acknowledged'}
            <p class="light-hint" role="status">L{lid}: {receiptLabel($lightCommandResults[lid].status)}</p>
          {/if}
        {/each}
      {/if}
    {:else}
    {#if compact}<p class="light-hint">Drag to dim · tap power or color</p>{/if}
    <div class="fixture-grid">
      {#each fixtureIds as lightId (lightId)}
        <div class="fixture" class:identified={$lights[lightId]?.reachable === true} aria-label={`Light L${lightId}`}>
          <div class="fixture-heading"><span class="fixture-id">L{lightId}</span></div>
          {#if $lights[lightId] && $lights[lightId].reachable === true}
            <LightCard light={$lights[lightId]} optimisticStore={false} />
          {:else}
            <p role="status" class="warning">{ $lights[lightId] ? 'Light unavailable' : 'Waiting for light status' }</p>
          {/if}
        </div>
      {/each}
    </div>
    {/if}
  {/if}
  <details class="control-details">
    <summary>About these controls</summary>
    <p class="provenance">Adjust lights individually or control both kitchen lights together. Some adjustments may be blocked while another lighting effect is active.</p>
    <p class="footnote">If a light doesn’t respond, check its connection and current lighting mode.</p>
  </details>
</section>

<style>
  .room-control {grid-column:1 / -1;min-width:0;}
  .sr-only {position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;border:0;}
  .provenance,.footnote { font-size:13px;line-height:1.6;color:var(--muted);max-width:70ch; }
  .kitchen-switch {display:flex;gap:4px;padding:4px;margin:0 0 10px;border-radius:14px;background:rgba(255,255,255,.06);}
  .kitchen-switch button {flex:1;min-width:0;min-height:44px;border:1px solid transparent;border-radius:11px;background:transparent;color:var(--muted);font:inherit;cursor:pointer;}
  .kitchen-switch button[aria-pressed="true"] {background:rgba(237,207,160,.12);border-color:var(--line);color:var(--ink);}
  .kitchen-switch button:focus-visible {outline:3px solid var(--gold);outline-offset:2px;}
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
