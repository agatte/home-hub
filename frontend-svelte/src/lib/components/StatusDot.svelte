<script>
  export let active = false
  /** @type {string | undefined} */
  export let label = undefined
</script>

<div class="status-dot-container">
  <span class="status-dot" class:status-active={active} class:status-inactive={!active} />
  {#if label}
    <span class="status-label">{label}</span>
  {/if}
</div>
