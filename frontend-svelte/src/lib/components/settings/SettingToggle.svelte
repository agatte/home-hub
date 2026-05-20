<script>
  export let checked = false
  export let disabled = false
  /** @type {string | undefined} */
  export let saving = undefined
  /** @type {string} */
  export let label = ''
  /** @type {(value: boolean) => void} */
  export let onChange = () => {}

  function flip() {
    if (disabled) return
    onChange(!checked)
  }
</script>

<button
  type="button"
  class="settings-toggle"
  class:on={checked}
  {disabled}
  aria-pressed={checked}
  aria-label={label || (checked ? 'On' : 'Off')}
  on:click={flip}
>
  <span class="toggle-track">
    <span class="toggle-thumb"></span>
  </span>
  <span class="toggle-label">
    {#if saving}…{:else}{checked ? 'ON' : 'OFF'}{/if}
  </span>
</button>

<style>
  .settings-toggle {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    background: transparent;
    border: 0;
    padding: 4px 0;
    cursor: pointer;
    color: var(--text-secondary);
    font-family: var(--font-body);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
  }

  .settings-toggle:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .toggle-track {
    position: relative;
    width: 40px;
    height: 22px;
    border-radius: 22px;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid var(--border);
    transition: background 0.2s, border-color 0.2s;
  }

  .toggle-thumb {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--text-secondary);
    transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1), background 0.2s;
  }

  .settings-toggle.on .toggle-track {
    background: rgba(74, 108, 247, 0.32);
    border-color: var(--accent);
  }

  .settings-toggle.on .toggle-thumb {
    transform: translateX(18px);
    background: var(--accent);
  }

  .settings-toggle.on {
    color: var(--text-primary);
  }

  .settings-toggle:hover:not(:disabled) .toggle-track {
    border-color: var(--accent);
  }

  .toggle-label {
    min-width: 26px;
    text-align: left;
  }
</style>
