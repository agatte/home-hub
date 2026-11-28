<script>
  import { onMount } from 'svelte'
  import { Music, Wifi, Wine, Sprout, Sparkles, ArrowUpRight, ChevronRight } from 'lucide-svelte'
  import { guestState, initGuestState } from '$lib/stores/guest.js'

  const HOUSE_RULES = [
    'Make yourself at home — fridge and bar are open.',
    'Bathroom is past the kitchen on the left.',
    'Lights and music change with the room — that\'s normal.',
    'Cheers — let\'s get fucked up.',
  ]

  $: sonos = $guestState.sonos
  $: nowPlaying = sonos?.state === 'PLAYING' && (sonos?.track || sonos?.artist)

  onMount(() => initGuestState())
</script>

<svelte:head><title>Welcome — HomeHub</title></svelte:head>

<main class="welcome-page">
  <section class="welcome-hero" aria-labelledby="welcome-title">
    <div class="hero-arch" aria-hidden="true"></div>
    <div class="hero-content">
      <p class="eyebrow">Make yourself at home</p>
      <h1 id="welcome-title">Welcome in<span>.</span></h1>
      <p class="hero-copy">Get connected, find something to drink, and make yourself comfortable.</p>
      <a class="wifi-cta" href="/guest/wifi">
        <Wifi size={21} strokeWidth={1.7} aria-hidden="true" />
        <span>Connect to Wi-Fi</span>
        <ChevronRight size={19} aria-hidden="true" />
      </a>
    </div>
  </section>

  <section class="music-feature" aria-labelledby="music-title">
    <div class="feature-top">
      <div>
        <p class="eyebrow">The sound of the evening</p>
        <h2 id="music-title">Now playing</h2>
      </div>
      <Music size={24} strokeWidth={1.5} aria-hidden="true" />
    </div>
    <div class="track">
      {#if nowPlaying && sonos?.has_art}
        <img class="art" src={`/api/guest/art?track=${encodeURIComponent(sonos?.track || '')}`} alt="Album artwork" />
      {:else}
        <div class="art art-placeholder" aria-hidden="true"><Music size={30} strokeWidth={1.35} /></div>
      {/if}
      <div class="track-copy">
        {#if nowPlaying}
          <strong>{sonos?.track || 'Track information unavailable'}</strong>
          {#if sonos?.artist}<span>{sonos.artist}</span>{/if}
        {:else if sonos?.state === 'disconnected' || !sonos?.state}
          <strong>Music status unavailable</strong>
          <span>Explore music and lighting in Vibe.</span>
        {:else if sonos?.state === 'PLAYING'}
          <strong>Music is playing</strong><span>Track information unavailable.</span>
        {:else}
          <strong>Nothing playing right now</strong><span>Make the evening your own.</span>
        {/if}
      </div>
    </div>
    <a class="music-link" href="/guest/vibe">Music &amp; atmosphere <ArrowUpRight size={16} aria-hidden="true" /></a>
  </section>

  <section class="explore" aria-labelledby="explore-title">
    <div class="section-heading"><p class="eyebrow">Your evening</p><h2 id="explore-title">Explore the apartment</h2></div>
    <div class="destinations">
      <a class="destination bar" href="/guest/bar">
        <div class="destination-top"><Wine size={27} strokeWidth={1.5} aria-hidden="true" /><ArrowUpRight size={17} aria-hidden="true" /></div>
        <div><h3>The bar</h3><p>Find your next drink</p></div>
      </a>
      <a class="destination plants" href="/guest/plants">
        <div class="destination-top"><Sprout size={27} strokeWidth={1.5} aria-hidden="true" /><ArrowUpRight size={17} aria-hidden="true" /></div>
        <div><h3>The plants</h3><p>See what's growing</p></div>
      </a>
      <a class="destination vibe" href="/guest/vibe">
        <div class="destination-top"><Sparkles size={27} strokeWidth={1.5} aria-hidden="true" /><ArrowUpRight size={17} aria-hidden="true" /></div>
        <div><h3>Set the vibe</h3><p>Lights, music and atmosphere</p></div>
      </a>
    </div>
  </section>

  <section class="house-notes" aria-labelledby="notes-title">
    <div class="section-heading"><p class="eyebrow">A few little things</p><h2 id="notes-title">House notes</h2></div>
    <ul>
      {#each HOUSE_RULES as rule}<li>{rule}</li>{/each}
    </ul>
  </section>
</main>

<style>
  .welcome-page {max-width:1000px;margin:0 auto;display:grid;gap:18px;min-width:0;}
  .welcome-hero,.music-feature,.house-notes {position:relative;min-width:0;border:1px solid var(--guest-line);border-radius:24px;padding:clamp(20px,4vw,34px);}
  .welcome-hero {overflow:hidden;isolation:isolate;min-height:286px;display:flex;align-items:center;background:radial-gradient(ellipse at 84% 8%,#53644a 0%,transparent 57%),linear-gradient(135deg,#263c31,#1a2822);}
  .hero-arch {position:absolute;z-index:-1;inset:19px -38px -75px 53%;border:1px solid rgba(228,201,158,.24);border-radius:48% 48% 0 0;transform:rotate(-10deg);box-shadow:0 0 0 15px rgba(228,201,158,.035),0 0 0 31px rgba(228,201,158,.025);}
  .hero-content {position:relative;max-width:420px;}
  .eyebrow {font-size:10px;line-height:1.4;font-weight:750;letter-spacing:.15em;text-transform:uppercase;color:var(--guest-gold);margin:0 0 8px;}
  h1,h2,h3,p {margin:0;}
  h1 {font:400 clamp(46px,8vw,76px)/.99 var(--guest-display);letter-spacing:-.055em;color:var(--guest-ink);}
  h1 span {color:var(--guest-gold);}
  .hero-copy {font-size:15px;line-height:1.6;color:#e0e5d8;max-width:300px;margin-top:14px;}
  .wifi-cta {display:inline-flex;align-items:center;justify-content:space-between;gap:12px;min-height:48px;max-width:100%;margin-top:24px;padding:12px 15px;background:var(--guest-gold);color:#233027;font-size:14px;font-weight:700;border-radius:13px;text-decoration:none;}
  .wifi-cta:hover {background:#f4dcb2;}
  .music-feature,.house-notes {background:var(--guest-surface);}
  .music-feature {display:flex;flex-direction:column;gap:19px;}
  .feature-top,.destination-top {display:flex;align-items:flex-start;justify-content:space-between;gap:10px;color:var(--guest-gold);}
  h2 {font:400 clamp(25px,4vw,34px)/1.1 var(--guest-display);letter-spacing:-.025em;color:var(--guest-ink);}
  .track {display:flex;align-items:center;gap:15px;min-width:0;flex:1;}
  .art {width:76px;height:76px;border-radius:14px;object-fit:cover;flex:none;}
  .art-placeholder {display:grid;place-items:center;color:#e4c99e;background:linear-gradient(145deg,#445c49,#283a31);}
  .track-copy {display:grid;gap:6px;min-width:0;}
  .track-copy strong {font-size:16px;line-height:1.35;overflow-wrap:anywhere;}
  .track-copy span,.destination p {font-size:13px;line-height:1.45;color:var(--guest-muted);overflow-wrap:anywhere;}
  .music-link {min-height:44px;display:flex;align-items:center;justify-content:space-between;gap:10px;text-decoration:none;color:var(--guest-gold);border-top:1px solid var(--guest-line);padding-top:10px;font-size:14px;font-weight:650;}
  .explore {display:grid;gap:13px;min-width:0;}
  .section-heading {padding:4px 2px;}
  .destinations {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;}
  .destination {display:flex;flex-direction:column;justify-content:space-between;min-height:138px;gap:20px;padding:17px;min-width:0;border-radius:18px;border:1px solid var(--guest-line);color:var(--guest-ink);text-decoration:none;}
  .destination:hover {filter:brightness(1.1);}
  .destination h3 {font:400 clamp(22px,3vw,29px)/1.1 var(--guest-display);margin-bottom:5px;}
  .destination.bar {background:linear-gradient(145deg,#52382d,#342820);}
  .destination.bar .destination-top {color:#edc4a7;}
  .destination.plants {background:linear-gradient(145deg,#344b38,#25362d);}
  .destination.plants .destination-top {color:#bfd7b8;}
  .destination.vibe {grid-column:1/-1;min-height:112px;background:linear-gradient(145deg,#433747,#292a35);}
  .destination.vibe .destination-top {color:#e0c6ef;}
  .house-notes ul {display:grid;gap:0;list-style:none;margin:12px 0 0;padding:0;}
  .house-notes li {font-size:14px;line-height:1.55;color:var(--guest-muted);padding:12px 0;border-top:1px solid var(--guest-line);}
  @media(min-width:760px) {
    .welcome-page {grid-template-columns:minmax(0,1.32fr) minmax(0,1fr);gap:18px;}
    .welcome-hero {min-height:320px;}
    .explore,.house-notes {grid-column:1/-1;}
    .destinations {grid-template-columns:repeat(3,minmax(0,1fr));}
    .destination.vibe {grid-column:auto;min-height:138px;}
    .house-notes ul {grid-template-columns:repeat(2,minmax(0,1fr));column-gap:26px;}
  }
  @media(max-width:360px) {.destination {padding:13px;}.welcome-hero,.music-feature,.house-notes {padding:18px;}.art {width:60px;height:60px;}}
</style>
