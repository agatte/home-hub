<script>
  /** @typedef {{id: string, label: string, icon?: any, hint?: string}} SectionDef */

  /** @type {SectionDef[]} */
  export let sections = []
  /** @type {string} */
  export let activeId = ''
  /** @type {(id: string) => void} */
  export let onSelect = () => {}

  /** @param {Event} event */
  function selectPhoneSection(event) {
    const target = event.currentTarget
    if (!(target instanceof HTMLSelectElement)) return
    if (sections.some(({ id }) => id === target.value)) onSelect(target.value)
  }
</script>

<aside class="settings-rail">
  <header class="rail-head">
    <h1>Settings</h1>
  </header>
  <div class="phone-section-picker">
    <label for="homehub-phone-settings-section">Choose a settings section</label>
    <select id="homehub-phone-settings-section" value={activeId} on:change={selectPhoneSection}>
      {#each sections as section (section.id)}
        <option value={section.id}>{section.label}</option>
      {/each}
    </select>
    <p>The section below contains the existing functional settings. Changing this menu only navigates.</p>
  </div>
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
  .phone-section-picker {display:none;}
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
    .settings-rail {position:static;max-height:none}
    .rail-nav {flex-direction:row;flex-wrap:wrap;gap:6px}
    .rail-item {flex:1 1 calc(50% - 6px);min-width:140px}
  }
  @media (max-width: 600px) {
    .settings-rail {position:static;box-sizing:border-box;min-width:0;max-height:none;overflow:visible;padding:15px;border-radius:15px;background:#17251c;border-color:rgba(167,194,165,.25)}
    .rail-head {margin-bottom:11px}
    .rail-head h1 {font-family:var(--font-body,system-ui);font-size:21px;font-weight:650;letter-spacing:0;line-height:1.25;color:#eef2e8}
    .rail-nav {display:none}
    .phone-section-picker {display:flex;flex-direction:column;gap:8px;min-width:0}
    .phone-section-picker label {font-size:13px;font-weight:650;color:#e6eddf}
    .phone-section-picker select {box-sizing:border-box;width:100%;min-width:0;min-height:52px;border:1px solid rgba(160,191,163,.5);border-radius:12px;background:#1b2c23;color:#f2f5eb;padding:12px 13px;font-family:var(--font-body,system-ui);font-size:16px}
    .phone-section-picker select:focus-visible {outline:3px solid #d5e7bd;outline-offset:3px}
    .phone-section-picker p {font-size:12px;line-height:1.5;color:#b9c9b8;margin:0}
  }
</style>
