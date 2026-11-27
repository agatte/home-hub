<script>
  import { connected, deviceStatus } from '$lib/stores/connection.js'
  import ApartmentViz from '$lib/components/ApartmentViz.svelte'
  import PlantWidget from '$lib/components/PlantWidget.svelte'
  import BarWidget from '$lib/components/BarWidget.svelte'
  import GuestWifiWidget from '$lib/components/GuestWifiWidget.svelte'
  import RoutineCard from '$lib/components/RoutineCard.svelte'
  import AmbientSoundWidget from '$lib/components/AmbientSoundWidget.svelte'
  import PiholeCard from '$lib/components/PiholeCard.svelte'
  import { CONTROL_SCENES_HREF } from '$lib/quietAtlas/navigation.js'
</script>

<svelte:head>
  <title>Household | HomeHub</title>
  <meta name="description" content="HomeHub household tools, routines, plants, bar, guests, ambient sound and network." />
</svelte:head>

<main class="household" aria-label="HomeHub household">
  <header class="heading">
    <p class="eyebrow">HOMEHUB / HOUSEHOLD</p>
    <h1>Household</h1>
    <p>Care for your space, set the atmosphere, and welcome guests.</p>
  </header>
  <nav class="jump" aria-label="Household sections">
    <a href="#household-care">Plants &amp; bar</a>
    <a href="#household-routines">Routines &amp; ambient</a>
    <a href="#household-guests">Guests &amp; network</a>
    <a href="#household-apartment">Apartment</a>
  </nav>

  <section class="household-section" id="household-care" aria-labelledby="care-heading">
    <div class="section-heading"><p class="eyebrow">01 / EVERYDAY</p><h2 id="care-heading">Care &amp; hospitality</h2></div>
    <div class="cards">
      <section class="house-card plant" aria-labelledby="plants-heading">
        <h3 id="plants-heading">Plants</h3>
        <p class="description">Care and watering overview.</p>
        <PlantWidget />
      </section>
      <section class="house-card bar" aria-labelledby="bar-heading">
        <h3 id="bar-heading">Home bar</h3>
        <p class="description">Inventory, cocktails and orders.</p>
        <BarWidget />
      </section>
    </div>
  </section>

  <section class="household-section" id="household-routines" aria-labelledby="routines-heading">
    <div class="section-heading"><p class="eyebrow">02 / RHYTHM</p><h2 id="routines-heading">Routines &amp; atmosphere</h2></div>
    <div class="cards">
      <section class="house-card" aria-labelledby="routine-heading">
        <h3 id="routine-heading">Routines</h3>
        <p class="description">Configured morning routine. Testing can run real actions.</p>
        <RoutineCard />
      </section>
      <section class="house-card" aria-labelledby="ambient-heading">
        <h3 id="ambient-heading">Ambient sound</h3>
        <p class="description">Soundscape, volume and weather-reactive audio.</p>
        <AmbientSoundWidget />
      </section>
    </div>
  </section>

  <section class="household-section" id="household-guests" aria-labelledby="guests-heading">
    <div class="section-heading"><p class="eyebrow">03 / CONNECTION</p><h2 id="guests-heading">Guests &amp; network</h2></div>
    <div class="cards">
      <section class="house-card" aria-labelledby="wifi-heading">
        <h3 id="wifi-heading">Guest Wi-Fi</h3>
        <p class="description">Use the existing guest QR tools when needed.</p>
        <GuestWifiWidget quietAtlas />
      </section>
      <section class="house-card" aria-labelledby="network-heading">
        <h3 id="network-heading">Network</h3>
        <p class="description">Reported Pi-hole statistics.</p>
        <PiholeCard />
      </section>
    </div>
  </section>

  <section class="household-section" id="household-apartment" aria-labelledby="apartment-heading">
    <div class="section-heading"><p class="eyebrow">04 / SPACE</p><h2 id="apartment-heading">Apartment</h2></div>
    <div class="house-card apartment">
      <div>
        <h3>Lighting overview</h3>
        <p class="description">Existing schematic with last reported fixture values. Missing values may appear unlit; this is not a measured floor plan or physical confirmation.</p>
      </div>
      {#if $connected && $deviceStatus.hue}
        <ApartmentViz />
      {:else}
        <p class="description" role="status">Lighting connection unavailable. Schematic state hidden.</p>
      {/if}
      <div class="jump">
        <a href="/quiet-atlas/control">Room and fixture controls</a>
        <a href={CONTROL_SCENES_HREF}>Scenes &amp; presets</a>
      </div>
    </div>
  </section>

  <details class="fallback">
    <summary>Temporary compatibility tools</summary>
    <p>Classic is retained while remaining capabilities are migrated and verified. It is not the permanent household interface.</p>
    <a href="/classic">Open temporary Classic fallback</a>
  </details>
</main>

<style>
  .household {
    display:grid;gap:26px;max-width:1400px;min-width:0;margin:0 auto;padding:clamp(18px,3vw,42px) var(--hh-gutter) 44px;
    color:var(--hh-ink);--bg-primary:var(--hh-panel-deep);--bg-secondary:var(--hh-panel);--bg-card:var(--hh-card-background);
    --bg-card-hover:var(--hh-control-hover);--text-primary:var(--hh-ink);--text-secondary:var(--hh-muted);--text-muted:var(--hh-muted);
    --accent:var(--hh-accent);--border:var(--hh-line);--radius:var(--hh-radius-panel);--radius-sm:var(--hh-radius-control);--font-body:var(--hh-font);
  }
  .heading,.section-heading {display:grid;gap:7px;}
  .eyebrow {font-size:11px;font-weight:750;letter-spacing:.14em;color:var(--hh-accent);}
  h1 {font:500 clamp(36px,5vw,60px)/1.1 var(--hh-display);letter-spacing:-.04em;}
  h2 {font:500 clamp(24px,3vw,34px)/1.15 var(--hh-display);}
  h3 {font-size:17px;font-weight:650;line-height:1.3;}
  .heading p:not(.eyebrow),.description,.fallback p {font-size:13px;line-height:1.55;color:var(--hh-muted);}
  .household-section {display:grid;gap:12px;min-width:0;scroll-margin-top:84px;}
  .cards {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;}
  .house-card {min-width:0;display:flex;flex-direction:column;gap:10px;padding:clamp(16px,2vw,24px);background:var(--hh-card-background);border:1px solid var(--hh-line);border-radius:var(--hh-radius-panel);}
  .plant {background:linear-gradient(145deg,rgba(69,106,73,.22),transparent 70%),var(--hh-card-background);}
  .bar {background:linear-gradient(145deg,rgba(128,76,46,.24),transparent 70%),var(--hh-card-background);}
  .apartment {gap:14px;}
  .apartment :global(.apartment-viz) {max-width:560px;width:100%;margin:0 auto;}
  .jump {display:flex;flex-wrap:wrap;gap:8px;min-width:0;}
  .jump a,.fallback a {display:inline-flex;align-items:center;min-height:44px;padding:8px 14px;border:1px solid var(--hh-line);border-radius:var(--hh-radius-control);color:var(--hh-ink);background:var(--hh-control);font-size:13px;text-decoration:none;}
  .jump a:hover,.fallback a:hover {background:var(--hh-control-hover);}
  .jump a:focus-visible,.fallback a:focus-visible,.fallback summary:focus-visible {outline:3px solid var(--hh-focus);outline-offset:3px;}
  .fallback {border:1px solid var(--hh-line);border-radius:var(--hh-radius-panel);padding:12px 16px;color:var(--hh-muted);}
  .fallback summary {min-height:44px;padding:10px 0;cursor:pointer;}
  .fallback a {margin-top:12px;}
  .house-card :global(button) {min-height:44px;}
  @media(max-width:800px) {.cards{grid-template-columns:minmax(0,1fr);}}
  @media(max-width:600px) {.household{gap:20px;padding:18px 16px 32px;}.jump a{flex:1 1 auto;justify-content:center;}.house-card{padding:16px;}}
</style>
