<script>
  import GuestWifiWidget from '$lib/components/GuestWifiWidget.svelte'
</script>

<svelte:head>
  <title>Network — Home Hub</title>
</svelte:head>

<main class="guest-page">
  <header class="guest-header">
    <h1>Network</h1>
    <p class="guest-subtitle">Scan to share with someone else</p>
  </header>

  <section class="guest-card">
    <GuestWifiWidget />
  </section>
</main>

<style>
  .guest-page {
    max-width: 540px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  .guest-header {
    text-align: center;
    margin-bottom: 4px;
  }

  .guest-header h1 {
    font-family: var(--font-display);
    font-size: 56px;
    line-height: 1;
    margin: 0 0 8px;
    letter-spacing: 0.04em;
    color: #fff;
  }

  .guest-subtitle {
    font-size: 14px;
    color: rgba(245, 243, 238, 0.65);
    margin: 0;
  }

  .guest-card {
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 18px;
    padding: 22px 24px;
    backdrop-filter: blur(12px);
  }

  @media (max-width: 480px) {
    .guest-header h1 {
      font-size: 44px;
    }
  }
</style>
