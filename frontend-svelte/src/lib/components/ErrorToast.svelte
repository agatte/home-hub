<script>
  import { errors } from '$lib/stores/errors.js'
  import { fly } from 'svelte/transition'
</script>

{#if $errors.length > 0}
  <div class="error-toast-stack">
    {#each $errors as error (error.id)}
      <div
        class="error-toast"
        role="status"
        aria-live="polite"
        aria-atomic="true"
        transition:fly={{ y: 30, duration: 250 }}
      >
        <svg class="error-toast-icon" width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
          <circle cx="10" cy="10" r="8" />
          <line x1="10" y1="6" x2="10" y2="11" />
          <circle cx="10" cy="14" r="0.5" fill="currentColor" />
        </svg>
        <span class="error-toast-text">{error.message}</span>
      </div>
    {/each}
  </div>
{/if}

<style>
  .error-toast-stack {
    position: fixed;
    bottom: 24px;
    left: 24px;
    z-index: 9000;
    display: flex;
    flex-direction: column;
    gap: 8px;
    width: min(340px, calc(100vw - 48px));
    pointer-events: none;
  }

  .error-toast {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 16px;
    background: rgba(220, 38, 38, 0.15);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(220, 38, 38, 0.3);
    border-radius: 12px;
    pointer-events: auto;
  }

  .error-toast-icon {
    color: #f87171;
    flex-shrink: 0;
  }

  .error-toast-text {
    font-family: var(--font-body);
    font-size: 13px;
    color: #fca5a5;
    line-height: 1.3;
  }

  @media (max-width: 768px) {
    .error-toast-stack {
      bottom: calc(164px + env(safe-area-inset-bottom, 0px));
      left: 12px;
      right: 12px;
      width: auto;
    }
  }

  @media (max-width: 480px) {
    .error-toast-stack {
      bottom: calc(148px + env(safe-area-inset-bottom, 0px));
    }
  }
</style>
