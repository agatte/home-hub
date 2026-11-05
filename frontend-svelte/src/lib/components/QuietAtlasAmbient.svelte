<script>
  import { onMount } from 'svelte'
  import { connected } from '$lib/stores/connection.js'

  import { wakeActivity } from '$lib/stores/activity.js'
  import { ambientContext, ambientContent, ambientClockText, ambientDateText } from '$lib/quietAtlas/ambient.js'
  import { installAmbientWakeGuard } from '$lib/quietAtlas/ambientWake.js'

  let now = new Date()
  let resumeButton
  $: content = ambientContent($connected, $ambientContext)
  $: time = ambientClockText(now)
  $: date = ambientDateText(now)
  $: step = Math.floor(now.getTime() / 900000) % 4

  onMount(() => {
    resumeButton.focus({ preventScroll: true })
    const timer = setInterval(() => { now = new Date() }, 15000)
    const removeGuard = installAmbientWakeGuard(window, wakeActivity)
    return () => { clearInterval(timer); removeGuard() }
  })
</script>

<section class="ambient" role="dialog" aria-modal="true" aria-label="HomeHub ambient display">
  <div class="readout" class:offset-one={step === 1} class:offset-two={step === 2} class:offset-three={step === 3}>
    <p class="eyebrow">HomeHub</p>
    <time class="clock">{time}</time>
    <p class="date">{date}</p>
    {#if content.house}
      <p class="context">HomeHub reports {content.house}{#if content.activity}<span> · {content.activity}</span>{/if}</p>
    {:else}
      <p class="context">HomeHub status unavailable</p>
    {/if}
   <button bind:this={resumeButton} type="button">Return to page</button>
  </div>
</section>

<style>
  .ambient { position: fixed; inset: 0; z-index: 10000; display: grid; place-items: center; background: #08130f; color: #c4cfc3; overflow: auto; overscroll-behavior: contain; touch-action: none; }
  .readout { text-align: center; max-width: 80vw; padding: 2rem; }
  .eyebrow { font-size: .8rem; letter-spacing: .24em; text-transform: uppercase; color: #829586; }
  .clock { display: block; font-size: clamp(5rem, 12vw, 11rem); font-weight: 300; font-variant-numeric: tabular-nums; line-height: 1.2; }
  .date { font-size: 1.3rem; color: #a0b19f; }
  .context { margin-top: 2.5rem; font-size: 1.2rem; }

  button { margin-top: 2rem; border: 1px solid #536758; background: transparent; color: #c4cfc3; border-radius: .4rem; padding: .7rem 1.2rem; font: inherit; cursor: pointer; }
  button:focus-visible { outline: 2px solid #c4cfc3; outline-offset: 5px; }
  .offset-one { transform: translate(8px, -8px); }
  .offset-two { transform: translate(8px, 8px); }
  .offset-three { transform: translate(-8px, 8px); }
  @media (prefers-reduced-motion: reduce) { .readout { transform: none; } }
</style>
