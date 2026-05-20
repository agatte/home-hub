<script>
  /** @typedef {{ip: string, hostname: string}} DnsHost */

  /** @type {DnsHost} */
  export let record
  /** @type {(record: DnsHost) => void} */
  export let onDelete = () => {}
  export let disabled = false
</script>

<div class="dns-row">
  <div class="dns-meta">
    <span class="dns-primary">{record.hostname}</span>
    <span class="dns-secondary">{record.ip}</span>
  </div>
  <button
    type="button"
    class="dns-remove"
    aria-label="Remove {record.hostname}"
    {disabled}
    on:click={() => onDelete(record)}
  >×</button>
</div>

<style>
  .dns-row {
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

  .dns-row:hover {
    background: rgba(255, 255, 255, 0.05);
    border-color: var(--border);
  }

  .dns-meta {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    flex: 1;
  }

  .dns-primary {
    font-family: var(--font-body);
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .dns-secondary {
    font-family: var(--font-body);
    font-size: 11px;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
  }

  .dns-remove {
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

  .dns-remove:hover:not(:disabled) {
    background: rgba(248, 113, 113, 0.25);
    border-color: var(--danger);
  }

  .dns-remove:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
