<script>
  import { slide } from 'svelte/transition'

  /** @type {string} */
  export let mode = ''
  /** @type {string} */
  export let label = ''
  /** @type {string | undefined} */
  export let icon = undefined
  /** @type {string | undefined} */
  export let summary = undefined
  /** @type {string | undefined} */
  export let accent = undefined
  export let expanded = false

  function toggle() {
    expanded = !expanded
  }
</script>

<div class="mode-accordion" class:expanded data-mode={mode}>
  <button type="button" class="mode-head" on:click={toggle} aria-expanded={expanded}>
    {#if icon}<span class="mode-icon" style:--mode-accent={accent || 'rgba(140, 100, 200, 0.5)'}>{icon}</span>{/if}
    <span class="mode-label">{label}</span>
    {#if summary}<span class="mode-summary">{summary}</span>{/if}
    <span class="mode-chevron" aria-hidden="true">›</span>
  </button>
  {#if expanded}
    <div class="mode-body" transition:slide={{ duration: 180 }}>
      <slot />
    </div>
  {/if}
</div>

<style>
  .mode-accordion {
    background: rgba(255, 255, 255, 0.025);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm, 10px);
    overflow: hidden;
    transition: border-color 0.2s, background 0.2s;
  }

  .mode-accordion.expanded {
    background: rgba(255, 255, 255, 0.04);
    border-color: var(--border-hover);
  }

  .mode-head {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px 16px;
    background: transparent;
    border: 0;
    color: var(--text-primary);
    cursor: pointer;
    font-family: var(--font-body);
    font-size: 14px;
    text-align: left;
    transition: background 0.18s;
  }

  .mode-head:hover {
    background: rgba(255, 255, 255, 0.03);
  }

  .mode-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: 8px;
    background: var(--mode-accent, rgba(140, 100, 200, 0.16));
    font-size: 16px;
    flex-shrink: 0;
  }

  .mode-label {
    flex: 1;
    font-weight: 500;
    letter-spacing: 0.01em;
  }

  .mode-summary {
    font-size: 12px;
    color: var(--text-muted);
    margin-right: 8px;
    white-space: nowrap;
  }

  .mode-chevron {
    display: inline-flex;
    width: 16px;
    height: 16px;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    font-size: 18px;
    transition: transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
    transform: rotate(90deg);
  }

  .mode-accordion.expanded .mode-chevron {
    transform: rotate(-90deg);
    color: var(--text-primary);
  }

  .mode-body {
    padding: 4px 16px 18px;
    border-top: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
</style>
