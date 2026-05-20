<script>
  /** @type {'primary' | 'ghost' | 'danger' | 'accent'} */
  export let variant = 'ghost'
  export let disabled = false
  export let loading = false
  /** @type {string | undefined} */
  export let title = undefined
  /** @type {'button' | 'submit'} */
  export let type = 'button'
</script>

<button
  {type}
  {title}
  class="settings-btn"
  class:btn-primary={variant === 'primary'}
  class:btn-ghost={variant === 'ghost'}
  class:btn-danger={variant === 'danger'}
  class:btn-accent={variant === 'accent'}
  disabled={disabled || loading}
  on:click
>
  {#if loading}
    <span class="btn-spinner" aria-hidden="true"></span>
  {/if}
  <slot />
</button>

<style>
  .settings-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 8px 16px;
    border-radius: var(--radius-sm, 10px);
    border: 1px solid var(--border);
    background: var(--bg-secondary);
    color: var(--text-primary);
    font-family: var(--font-body);
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.18s;
    white-space: nowrap;
    min-height: 36px;
  }

  .settings-btn:hover:not(:disabled) {
    border-color: var(--accent);
    color: var(--accent);
  }

  .settings-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-primary {
    background: var(--accent);
    border-color: var(--accent);
    color: white;
  }

  .btn-primary:hover:not(:disabled) {
    background: #3a5ce6;
    border-color: #3a5ce6;
    color: white;
  }

  .btn-accent {
    background: rgba(140, 100, 200, 0.22);
    border-color: rgba(140, 100, 200, 0.55);
    color: var(--text-primary);
  }

  .btn-accent:hover:not(:disabled) {
    background: rgba(140, 100, 200, 0.34);
    border-color: rgba(170, 130, 230, 0.7);
    color: var(--text-primary);
  }

  .btn-danger {
    color: var(--danger);
    border-color: rgba(248, 113, 113, 0.3);
  }

  .btn-danger:hover:not(:disabled) {
    background: rgba(248, 113, 113, 0.12);
    border-color: var(--danger);
    color: var(--danger);
  }

  .btn-spinner {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    border: 2px solid currentColor;
    border-right-color: transparent;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }
</style>
