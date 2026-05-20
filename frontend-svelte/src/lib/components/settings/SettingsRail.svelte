<script>
  /** @typedef {{id: string, label: string, icon?: any, hint?: string}} SectionDef */

  /** @type {SectionDef[]} */
  export let sections = []
  /** @type {string} */
  export let activeId = ''
  /** @type {(id: string) => void} */
  export let onSelect = () => {}
</script>

<aside class="settings-rail">
  <header class="rail-head">
    <h1>Settings</h1>
  </header>
  <nav class="rail-nav" aria-label="Settings sections">
    {#each sections as section (section.id)}
      <button
        type="button"
        class="rail-item"
        class:rail-active={activeId === section.id}
        on:click={() => onSelect(section.id)}
        aria-current={activeId === section.id ? 'page' : undefined}
      >
        {#if section.icon}
          <span class="rail-icon">
            <svelte:component this={section.icon} size={16} strokeWidth={1.75} />
          </span>
        {/if}
        <span class="rail-label">{section.label}</span>
      </button>
    {/each}
  </nav>
</aside>

<style>
  .settings-rail {
    background: rgba(20, 20, 32, 0.55);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: var(--radius, 14px);
    padding: 16px;
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    align-self: start;
    position: sticky;
    top: 24px;
    max-height: calc(100vh - 48px);
    overflow-y: auto;
  }

  .rail-head {
    margin-bottom: 14px;
  }

  .rail-head h1 {
    font-family: var(--font-display, 'Bebas Neue', sans-serif);
    font-size: 24px;
    margin: 0;
    letter-spacing: 0.05em;
    color: var(--text-primary);
  }

  .rail-nav {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .rail-item {
    width: 100%;
    text-align: left;
    background: transparent;
    border: 1px solid transparent;
    color: var(--text-secondary);
    padding: 10px 12px;
    border-radius: var(--radius-sm, 10px);
    cursor: pointer;
    transition: all 0.15s;
    display: flex;
    align-items: center;
    gap: 10px;
    font-family: var(--font-body);
    font-size: 13px;
    font-weight: 500;
  }

  .rail-item:hover {
    border-color: rgba(255, 255, 255, 0.08);
    background: rgba(255, 255, 255, 0.03);
    color: var(--text-primary);
  }

  .rail-active {
    border-color: rgba(140, 100, 200, 0.5);
    background: rgba(140, 100, 200, 0.14);
    color: var(--text-primary);
  }

  .rail-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    flex-shrink: 0;
    opacity: 0.85;
  }

  .rail-label {
    flex: 1;
    min-width: 0;
  }

  @media (max-width: 900px) {
    .settings-rail {
      position: static;
      max-height: none;
    }

    .rail-nav {
      flex-direction: row;
      flex-wrap: wrap;
      gap: 6px;
    }

    .rail-item {
      flex: 1 1 calc(50% - 6px);
      min-width: 140px;
    }
  }
</style>
