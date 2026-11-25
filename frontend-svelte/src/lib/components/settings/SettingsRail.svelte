<script>
  import { tick } from 'svelte'
  import { ChevronDown, ChevronRight, Check } from 'lucide-svelte'
  /** @typedef {{id: string, label: string, icon?: any, hint?: string, group?: string}} SectionDef */
  /** @type {SectionDef[]} */
  export let sections = []
  /** @type {string} */
  export let activeId = ''
  /** @type {(id: string) => void} */
  export let onSelect = () => {}

  let menuOpen = false
  /** @type {HTMLButtonElement | null} */
  let menuButton = null
  $: groups = [...new Set(sections.map(section => section.group || 'Settings'))]
  $: activeSection = sections.find(section => section.id === activeId)

  /** @param {string} id */
  async function chooseSection(id) {
    if (!sections.some(section => section.id === id)) return
    const wasOpen = menuOpen
    menuOpen = false
    if (id !== activeId) onSelect(id)
    if (wasOpen) {
      await tick()
      menuButton?.focus()
    }
  }
</script>

<aside class="settings-rail">
  <header class="rail-head">
    <h2>Settings sections</h2>
    <p>Choose what to configure.</p>
  </header>
  <button type="button" class="phone-section-trigger" aria-expanded={menuOpen} aria-controls="homehub-settings-sections" bind:this={menuButton} on:click={() => menuOpen = !menuOpen}>
    {#if activeSection?.icon}
      <span class="rail-icon current-icon"><svelte:component this={activeSection.icon} size={20} strokeWidth={1.75} /></span>
    {/if}
    <span class="trigger-copy"><small>{activeSection?.group || 'Settings'}</small><strong>{activeSection?.label || 'Choose a section'}</strong></span>
    <span class="trigger-action">{menuOpen ? 'Close' : 'Change'}</span>
    <span class="trigger-chevron" class:open={menuOpen}><ChevronDown size={18} /></span>
  </button>
  <nav id="homehub-settings-sections" class="rail-nav" class:menu-open={menuOpen} aria-label="Settings sections">
    {#each groups as group (group)}
      <div class="rail-group" data-group={group}>
        <h3>{group}</h3>
        {#each sections.filter(section => (section.group || 'Settings') === group) as section (section.id)}
          <button type="button" class="rail-item" class:rail-active={activeId === section.id} on:click={() => chooseSection(section.id)} aria-current={activeId === section.id ? 'page' : undefined}>
            {#if section.icon}
              <span class="rail-icon"><svelte:component this={section.icon} size={19} strokeWidth={1.75} /></span>
            {/if}
            <span class="rail-copy">
              <span class="rail-label">{section.label}</span>
              {#if section.hint}<span class="rail-hint">{section.hint}</span>{/if}
            </span>
            <span class="rail-end" aria-hidden="true">{#if activeId === section.id}<Check size={15}/>{:else}<ChevronRight size={15}/>{/if}</span>
          </button>
        {/each}
      </div>
    {/each}
  </nav>
</aside>

<style>
  .settings-rail{min-width:0;position:sticky;top:24px;max-height:calc(100vh - 48px);overflow-y:auto;align-self:start;padding:0 8px 10px 0;}
  .rail-head{padding:0 10px 12px;}
  .rail-head h2{font-size:17px;letter-spacing:-.025em;font-weight:650;color:var(--text-primary);margin:0;}
  .rail-head p{color:var(--text-muted);font-size:12px;margin:5px 0 0;}
  .rail-nav{display:grid;gap:16px;}
  .rail-group{display:grid;gap:2px;--category-color:#9ebbad;}
  .rail-group[data-group="How HomeHub behaves"]{--category-color:#e5bd7e;}
  .rail-group[data-group="Listening & experiences"]{--category-color:#c7b5df;}
  .rail-group h3{font-size:12px;font-weight:650;color:var(--text-muted);margin:0 10px 5px;}
  .rail-item{box-sizing:border-box;width:100%;min-width:0;min-height:56px;display:flex;align-items:center;gap:10px;text-align:left;border:1px solid transparent;border-radius:12px;padding:8px 10px;background:transparent;color:var(--text-primary);font:inherit;cursor:pointer;}
  .rail-item:hover{background:var(--bg-card-hover);border-color:var(--border);}
  .rail-item.rail-active{background:var(--bg-card-hover);border-color:var(--border);color:var(--accent);}
  .rail-icon{display:grid;place-items:center;width:34px;height:34px;flex-shrink:0;border-radius:10px;color:var(--category-color,#d9c6a1);background:color-mix(in srgb,var(--category-color,#d9c6a1) 13%,transparent);}
  .rail-copy{flex:1;min-width:0;display:grid;gap:3px;overflow-wrap:anywhere;}
  .rail-label{font-size:14px;font-weight:600;line-height:1.3;}
  .rail-hint{font-size:11px;line-height:1.35;color:var(--text-muted);}
  .rail-end{display:flex;color:var(--text-muted);flex-shrink:0;}
  .rail-active .rail-end{color:var(--accent);}
  .phone-section-trigger{display:none;}
  .rail-item:focus-visible,.phone-section-trigger:focus-visible{outline:3px solid var(--hh-focus,#d5e7bd);outline-offset:2px;}
  @media(max-width:1120px){
    .settings-rail{position:static;max-height:none;overflow:visible;padding:0;}
    .rail-head{display:none;}
    .phone-section-trigger{display:flex;align-items:center;text-align:left;gap:11px;box-sizing:border-box;width:100%;min-height:64px;padding:12px;border:1px solid var(--border);border-radius:15px;background:var(--bg-card);color:var(--text-primary);font:inherit;cursor:pointer;}
    .trigger-copy{display:grid;gap:4px;flex:1;min-width:0;overflow-wrap:anywhere;}
    .trigger-copy small{font-size:11px;color:var(--text-muted);}
    .trigger-copy strong{font-size:16px;font-weight:650;}
    .trigger-action{font-size:12px;color:var(--accent);}
    .trigger-chevron{display:flex;color:var(--accent);flex-shrink:0;}
    .trigger-chevron.open{transform:rotate(180deg);}
    .rail-nav{display:none;}
    .rail-nav.menu-open{display:grid;gap:14px;margin:10px 0 0;padding:12px 4px;}
    .rail-item{min-height:56px;}
    .rail-hint{font-size:12px;}
  }
</style>
