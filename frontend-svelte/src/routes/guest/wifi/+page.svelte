<script>
  import GuestWifiWidget from '$lib/components/GuestWifiWidget.svelte'
</script>

<svelte:head>
  <title>Network — Home Hub</title>
</svelte:head>

<main class="guest-page">
  <header class="guest-header">
    <h1>Get connected.</h1>
    <p class="guest-subtitle">Join the guest Wi-Fi or share it with a friend.</p>
  </header>

  <section class="guest-card">
    <GuestWifiWidget quietAtlas />
  </section>
</main>

<style>
  .guest-page {
    max-width: 680px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }

  .guest-header {
    text-align: left; margin-bottom: 4px; padding: 4px 2px 8px;
  }

  .guest-header h1 {
    font-family: var(--font-display);
    font-size: clamp(38px, 7vw, 60px);
    line-height: 1;
    margin: 0 0 8px;
    letter-spacing: -0.035em;
    color: var(--guest-ink);
  }

  .guest-subtitle {
    font-size: 14px;
    color: var(--guest-muted);
    margin: 0;
  }

  .guest-card {
    background: var(--guest-surface);
    border: 1px solid var(--guest-line);
    border-radius: 20px;
    padding: clamp(17px, 4vw, 26px);
    backdrop-filter: blur(12px);
  }

  @media (max-width: 480px) {
    .guest-header h1 {
      font-size: clamp(36px, 9vw, 44px);
    }
  }
  .guest-card :global(.wifi-link) {min-height:44px;padding:8px 12px;border:1px solid var(--guest-line);border-radius:10px;margin-top:8px;}
  .guest-card :global(.wifi-hint) {display:none;}
</style>
