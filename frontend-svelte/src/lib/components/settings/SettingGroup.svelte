<script>
  /** @type {string} */
  export let title = ''
  /** @type {string | undefined} */
  export let hint = undefined
</script>

<div class="setting-group">
  {#if title}
    <header class="group-head">
      <h3 class="group-title">{title}</h3>
      {#if hint}<p class="group-hint">{hint}</p>{/if}
    </header>
  {/if}
  <div class="group-body">
    <slot />
  </div>
</div>

<style>
  .setting-group {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .setting-group + :global(.setting-group) {
    margin-top: 12px;
    padding-top: 18px;
    border-top: 1px solid var(--border);
  }

  .group-head {
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin-bottom: 4px;
  }

  .group-title {
    font-family: var(--font-body);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--text-muted);
    margin: 0;
  }

  .group-hint {
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--text-muted);
    margin: 0;
    line-height: 1.5;
  }

  .group-body {
    display: flex;
    flex-direction: column;
    gap: 0;
  }
</style>
