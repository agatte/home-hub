<script>
  import { lights } from '$lib/stores/lights.js'
  import { connected, deviceStatus } from '$lib/stores/connection.js'
  import LightCard from './LightCard.svelte'

  /** Existing HomeHub fixture IDs, not a new actuation authority. */
  export let room
  export let id

  // Each card sends one existing light_command over HomeHub's WebSocket.
  // No paired Kitchen commands: each card addresses its own fixture.
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
</script>

<section class="room-control" aria-labelledby={`${id}-heading`}>
  <div class="heading-row">
    <h4 id={`${id}-heading`}>Live {roomLabel} lighting</h4>
    <span class:online={$connected} class="connection">{ $connected ? 'Hub connected' : 'Hub disconnected' }</span>
  </div>
  <p class="provenance">HomeHub-reported values only. A control sends a request, not a confirmed result: if a stronger lighting owner is active, the server may deny the change. Room expansion itself never changes a light.</p>
  {#if !$connected}
    <p role="status" class="warning">Lighting commands are unavailable while HomeHub is disconnected. Reconnect before adjusting.</p>
  {:else if $deviceStatus.light_command_results !== true}
    <p role="status" class="warning">This HomeHub server does not yet support guarded lighting command results. These redesigned controls will stay unavailable until the matching server update. The original Apartment controls remain accessible below.</p>
  {:else if fixtureIds.length === 0}
    <p role="status" class="warning">No configured fixtures for this room.</p>
  {:else}
    <div class="fixture-grid">
      {#each fixtureIds as lightId (lightId)}
        <div class="fixture" aria-label={`Light L${lightId}`}>
          <div class="fixture-heading"><strong>L{lightId}</strong><span>{ $lights[lightId]?.name ?? 'No current reading' }</span></div>
          {#if $lights[lightId] && $lights[lightId].reachable === true}
            <LightCard light={$lights[lightId]} optimisticStore={false} />
          {:else}
            <p role="status" class="warning">{ $lights[lightId] ? 'Fixture unreachable — controls unavailable' : 'Waiting for fixture state — controls unavailable' }</p>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
  <p class="footnote">Bedroom and Kitchen fixtures are individually addressable. Guarded WebSocket receipts report server decisions, never physical completion. Server-side ownership changes and kiosk/iPhone acceptance require their own reviewed release.</p>
  <a href="/classic#apartment-controls">Original Apartment controls</a>
</section>

<style>
  .room-control { grid-column:1 / -1; min-width:0; border-top:1px solid var(--line);padding-top:16px; }
  .heading-row { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:12px; }
  h4 { font-size:19px; line-height:1.3; font-weight:650; margin:0; }
  .connection { font-size:12px; color:var(--muted); }
  .connection.online { color:var(--gold); }
  .provenance,.footnote { font-size:13px;line-height:1.6;color:var(--muted);max-width:70ch; }
  .fixture-grid { display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:18px;min-width:0;margin:18px 0; }
  .fixture { min-width:0;padding:14px;border:1px solid var(--line);border-radius:12px; }
  .fixture-heading { display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:14px;margin-bottom:12px; }
  .fixture-heading span { color:var(--muted); }
  .warning { font-size:14px; line-height:1.5; padding:14px; border:1px solid var(--line);border-radius:8px; }
  a {display:inline-flex;align-items:center;min-height:44px;font-size:14px;color:var(--gold);text-decoration:underline;text-underline-offset:4px; }
  a:focus-visible {outline:3px solid var(--gold);outline-offset:3px;}
  :global(.room-control .light-card-owner) {min-width:0;max-width:100%;}
  @media(max-width:700px) {.fixture-grid {grid-template-columns:minmax(0,1fr);} .fixture{padding:12px;}}
</style>
