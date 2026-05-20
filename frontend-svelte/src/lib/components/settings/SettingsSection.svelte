<script>
  /** @type {string} */
  export let title = ''
  /** @type {string | undefined} */
  export let description = undefined
  /** @type {any} */
  export let icon = undefined
  /** When true, skip the inner padding so child components own framing.
   *  Used when the slot contains a self-framed widget (e.g. AmbientSettings,
   *  ModePlaylistMapper, LearnedRulesCard). */
  export let flush = false
</script>

<section class="settings-section">
  <header class="section-head">
    {#if icon}
      <span class="section-icon">
        <svelte:component this={icon} size={18} strokeWidth={1.75} />
      </span>
    {/if}
    <div class="section-titlewrap">
      <h2 class="section-title">{title}</h2>
      {#if description}
        <p class="section-description">{description}</p>
      {/if}
    </div>
  </header>
  <div class="section-body" class:flush>
    <slot />
  </div>
</section>

<style>
  .settings-section {
    background: rgba(20, 20, 32, 0.55);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: var(--radius, 14px);
    padding: 24px 28px 26px;
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    display: flex;
    flex-direction: column;
    gap: 18px;
    animation: sectionFade 0.32s cubic-bezier(0.34, 1.56, 0.64, 1) both;
  }

  @keyframes sectionFade {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .section-head {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding-bottom: 14px;
    border-bottom: 1px solid var(--border);
  }

  .section-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 8px;
    background: rgba(140, 100, 200, 0.16);
    color: rgba(190, 165, 235, 1);
    flex-shrink: 0;
  }

  .section-titlewrap {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .section-title {
    font-family: var(--font-display, 'Bebas Neue', sans-serif);
    font-size: 22px;
    letter-spacing: 0.04em;
    margin: 0;
    color: var(--text-primary);
  }

  .section-description {
    font-family: var(--font-body);
    font-size: 13px;
    color: var(--text-muted);
    margin: 0;
    line-height: 1.5;
  }

  .section-body {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .section-body.flush {
    margin: -4px -8px -6px;
    gap: 16px;
  }

  @media (max-width: 480px) {
    .settings-section {
      padding: 20px 18px 22px;
    }
  }
</style>
