<script>
  import { ChevronLeft, ChevronRight, Check } from 'lucide-svelte'
  /** @typedef {{id: string, label: string, icon?: any, hint?: string, group?: string}} SectionDef */
  /** @type {SectionDef[]} */
  export let sections = []
  /** @type {string} */
  export let activeId = ''
  /** @type {(id: string) => void} */
  export let onSelect = () => {}

  export let indexView = false
  export let indexHref = '/quiet-atlas/settings'
  $: groups = [...new Set(sections.map(section => section.group || 'Settings'))]
  $: activeSection = sections.find(section => section.id === activeId)

  /** @param {string} id */
  function chooseSection(id) {
    if (!sections.some(section => section.id === id)) return
    if (indexView || id !== activeId) onSelect(id)
  }
</script>

<aside class="settings-rail" class:index-view={indexView}>
  <header class="rail-head">
    <h2>Settings sections</h2>
    <p>Choose what to configure.</p>
  </header>
  {#if !indexView}
    <a class="section-back" href={indexHref} data-sveltekit-replacestate aria-label="Back to Settings sections">
      <ChevronLeft size={21} strokeWidth={2} aria-hidden="true" />
      <span>Settings</span>
      <span class="back-current">{activeSection?.label || ''}</span>
    </a>
  {/if}
  <nav id="homehub-settings-sections" class="rail-nav" aria-label="Settings sections">
    {#each groups as group (group)}
      <div class="rail-group" data-group={group}>
        <h3>{group}</h3>
        {#each sections.filter(section => (section.group || 'Settings') === group) as section (section.id)}
          <button type="button" class="rail-item" class:rail-active={!indexView && activeId === section.id} on:click={() => chooseSection(section.id)} aria-current={!indexView && activeId === section.id ? 'page' : undefined}>
            {#if section.icon}
              <span class="rail-icon"><svelte:component this={section.icon} size={19} strokeWidth={1.75} /></span>
            {/if}
            <span class="rail-copy">
              <span class="rail-label">{section.label}</span>
              {#if section.hint}<span class="rail-hint">{section.hint}</span>{/if}
            </span>
            <span class="rail-end" aria-hidden="true">{#if !indexView && activeId === section.id}<Check size={15}/>{:else}<ChevronRight size={15}/>{/if}</span>
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
  .section-back{display:none;}
  .rail-item:focus-visible,.section-back:focus-visible{outline:3px solid var(--hh-focus,#d5e7bd);outline-offset:2px;}
  @media(max-width:1120px){
    .settings-rail{position:sticky;top:0;z-index:10;max-height:none;overflow:visible;padding:0;background:var(--hh-chrome,#17251c);}
    .settings-rail.index-view{position:static;background:transparent;}
    .rail-head{display:none;}
    .section-back{display:flex;align-items:center;gap:8px;box-sizing:border-box;min-height:48px;padding:8px 12px;border:1px solid var(--border);border-radius:12px;background:var(--bg-card);color:var(--accent);text-decoration:none;font-size:15px;font-weight:650;}
    .back-current{margin-left:auto;min-width:0;overflow-wrap:anywhere;color:var(--text-muted);font-size:12px;font-weight:500;text-align:right;}
    .rail-nav{display:none;}
    .index-view .rail-nav{display:grid;gap:18px;}
    .rail-item{min-height:56px;}
    .rail-hint{font-size:12px;}
  }
  @media(max-width:760px){.settings-rail{top:66px;}}
</style>
