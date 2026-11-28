<script>
  import '$lib/styles/global.css'
  import '$lib/styles/homehub-surface.css'
  import GuestOwnerReturn from '$lib/components/GuestOwnerReturn.svelte'
  import GuestBottomNav from '$lib/components/GuestBottomNav.svelte'

  /** @type {any} */
  export let data = undefined
  /** @type {any} */
  export let params = undefined
  data; params;

</script>

<div class="guest-shell">
  <div class="guest-frame">
    <GuestOwnerReturn />
    <header class="guest-brand">
      <a href="/guest" aria-label="HomeHub guest welcome">Home<span>Hub</span></a>
      <span class="guest-edition">Guest guide</span>
    </header>
    <slot />
  </div>
  <GuestBottomNav />
</div>

<style>
  .guest-shell {
    --guest-canvas:#141b18;--guest-surface:linear-gradient(145deg,#26312b,#202823);
    --guest-ink:#f5f0e6;--guest-muted:#c3c9bd;--guest-gold:#e4c99e;
    --guest-line:rgba(229,220,197,.17);--guest-display:Georgia,"Times New Roman",serif;
    --font-display:var(--guest-display);--font-body:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
    --accent:var(--guest-gold);--text-primary:var(--guest-ink);--text-secondary:var(--guest-muted);--text-muted:var(--guest-muted);
    --bg-primary:var(--guest-canvas);--bg-secondary:#202823;--bg-card:#26312b;--border:var(--guest-line);
    min-height:100vh;min-height:100dvh;width:100%;color:var(--guest-ink);font-family:var(--font-body);
    background:radial-gradient(ellipse at 80% 0%,rgba(125,133,88,.15),transparent 45%),var(--guest-canvas);
    padding:clamp(18px,4vw,42px) max(14px,env(safe-area-inset-right)) calc(112px + env(safe-area-inset-bottom)) max(14px,env(safe-area-inset-left));
    box-sizing:border-box;
  }
  .guest-frame {max-width:1000px;margin:0 auto;min-width:0;}
  .guest-brand {display:flex;align-items:center;justify-content:space-between;gap:10px;padding:5px 2px 19px;}
  .guest-brand a {display:inline-flex;align-items:center;min-height:44px;color:var(--guest-ink);font-size:19px;font-weight:650;letter-spacing:-.04em;text-decoration:none;}
  .guest-brand a span {color:var(--guest-gold);}
  .guest-edition {color:var(--guest-gold);font-size:10px;letter-spacing:.15em;text-transform:uppercase;font-weight:750;}
  .guest-shell :global(a:focus-visible),.guest-shell :global(button:focus-visible) {outline:3px solid var(--guest-gold);outline-offset:3px;}
  :global(body) {margin:0;}
</style>
