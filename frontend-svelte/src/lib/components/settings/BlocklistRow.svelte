<script>
  /** @typedef {{address: string}} Blocklist */

  /** @type {Blocklist} */
  export let list
  /** @type {string} */
  export let label = ''
  /** @type {(address: string) => void} */
  export let onDelete = () => {}
  export let disabled = false
</script>

<div class="list-row">
  <div class="list-meta">
    <span class="list-primary">{label || list.address}</span>
    <span class="list-secondary">{list.address}</span>
  </div>
  <button
    type="button"
    class="list-remove"
    aria-label="Remove {label || list.address}"
    {disabled}
    on:click={() => onDelete(list.address)}
  >×</button>
</div>

<style>
  .list-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 8px 12px;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid transparent;
    transition: background 0.18s, border-color 0.18s;
  }

  .list-row:hover {
    background: rgba(255, 255, 255, 0.05);
    border-color: var(--border);
  }

  .list-meta {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    flex: 1;
  }

  .list-primary {
    font-family: var(--font-body);
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .list-secondary {
    font-family: var(--font-body);
    font-size: 11px;
    color: var(--text-muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .list-remove {
    flex-shrink: 0;
    width: 26px;
    height: 26px;
    border: 1px solid transparent;
    border-radius: 6px;
    background: rgba(248, 113, 113, 0.1);
    color: var(--danger);
    font-size: 16px;
    line-height: 1;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.18s;
  }

  .list-remove:hover:not(:disabled) {
    background: rgba(248, 113, 113, 0.25);
    border-color: var(--danger);
  }

  .list-remove:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
