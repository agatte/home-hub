<script>
  /** @type {string} */
  export let label = ''
  /** @type {string | undefined} */
  export let hint = undefined
  /** Render the control under the label instead of side-by-side. Use for wide
   *  controls like sliders or grids. */
  export let stacked = false
</script>

<div class="settings-row" class:stacked>
  <div class="row-info">
    <span class="row-label">{label}</span>
    {#if hint}<span class="row-hint">{hint}</span>{/if}
  </div>
  <div class="row-control">
    <slot />
  </div>
</div>

<style>
  .settings-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 14px 4px;
    min-width: 0;
  }

  .settings-row + :global(.settings-row) {
    border-top: 1px solid var(--border);
  }

  .settings-row.stacked {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }

  .row-info {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
    flex: 1;
  }

  .row-label {
    font-family: var(--font-body);
    font-size: 14px;
    font-weight: 500;
    color: var(--text-primary);
  }

  .row-hint {
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--text-muted);
    line-height: 1.45;
  }

  .row-control {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;
    min-width: 0;
  }

  .settings-row.stacked .row-control {
    justify-content: stretch;
    width: 100%;
  }

  @media (max-width: 600px) {
    .settings-row:not(.stacked) {
      flex-wrap: wrap;
    }
  }
</style>
