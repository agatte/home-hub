<script>
  import { page } from '$app/stores'
  import { goto } from '$app/navigation'
  import {
    Activity,
    Laptop,
    Sliders,
    Moon,
    Calendar,
    Palette,
    Music,
    Volume2,
    Network,
    Brain,
    Trophy,
  } from 'lucide-svelte'

  import SettingsLayout from '$lib/components/settings/SettingsLayout.svelte'
  import OverviewSection from '../../settings/sections/OverviewSection.svelte'
  import HostSection from '../../settings/sections/HostSection.svelte'
  import AutomationSection from '../../settings/sections/AutomationSection.svelte'
  import DndSection from '../../settings/sections/DndSection.svelte'
  import ScheduleSection from '../../settings/sections/ScheduleSection.svelte'
  import ModesSection from '../../settings/sections/ModesSection.svelte'
  import MusicSection from '../../settings/sections/MusicSection.svelte'
  import AudioSection from '../../settings/sections/AudioSection.svelte'
  import NetworkSection from '../../settings/sections/NetworkSection.svelte'
  import LearningSection from '../../settings/sections/LearningSection.svelte'
  import GameDaySection from '../../settings/sections/GameDaySection.svelte'

  const SECTIONS = [
    { id: 'overview',   label: 'Overview',          icon: Activity, group: 'Systems & access' },
    { id: 'host',       label: 'Host / Travel',     icon: Laptop, group: 'Systems & access' },
    { id: 'automation', label: 'Automation',        icon: Sliders, group: 'How HomeHub behaves' },
    { id: 'dnd',        label: 'Do Not Disturb',    icon: Moon, group: 'How HomeHub behaves' },
    { id: 'schedule',   label: 'Schedule',          icon: Calendar, group: 'How HomeHub behaves' },
    { id: 'modes',      label: 'Modes',             icon: Palette, group: 'How HomeHub behaves' },
    { id: 'music',      label: 'Music',             icon: Music, group: 'Listening & experiences' },
    { id: 'audio',      label: 'Audio',             icon: Volume2, group: 'Listening & experiences' },
    { id: 'network',    label: 'Network',           icon: Network, group: 'Systems & access' },
    { id: 'learning',   label: 'Learning',          icon: Brain, group: 'Listening & experiences' },
    { id: 'gameday',    label: 'Game Day',          icon: Trophy, group: 'Listening & experiences' },
  ]

  /** @type {string} */
  let activeId = 'overview'

  // The URL owns the selected section, including Back/Forward to a missing
  // or invalid ?section=. Never leave a stale section visible for another URL.
  $: {
    const fromUrl = $page.url.searchParams.get('section')
    activeId = fromUrl && SECTIONS.some((s) => s.id === fromUrl) ? fromUrl : 'overview'
  }

  /** @param {string} id */
  function select(id) {
    activeId = id
    const url = new URL(window.location.href)
    url.searchParams.set('section', id)
    goto(`${url.pathname}${url.search}`, { replaceState: false, keepFocus: true, noScroll: true })
  }

  // SvelteKit passes these implicit props — declare to silence Svelte warnings.
  /** @type {any} */
  export let data = undefined
  /** @type {any} */
  export let params = undefined
  data; params;
</script>

<svelte:head>
  <title>Settings | HomeHub</title>
</svelte:head>

<main class="settings-workspace" aria-label="HomeHub settings">
  <header class="workspace-head">
    <p class="eyebrow">HOMEHUB / CONFIGURE</p>
    <h1>Settings</h1>
    <p>Automation, preferences and the systems that support your home.</p>
  </header>
  <SettingsLayout sections={SECTIONS} {activeId} onSelect={select}>
  {#if activeId === 'overview'}
    <OverviewSection />
  {:else if activeId === 'host'}
    <HostSection />
  {:else if activeId === 'automation'}
    <AutomationSection />
  {:else if activeId === 'dnd'}
    <DndSection />
  {:else if activeId === 'schedule'}
    <ScheduleSection />
  {:else if activeId === 'modes'}
    <ModesSection />
  {:else if activeId === 'music'}
    <MusicSection />
  {:else if activeId === 'audio'}
    <AudioSection />
  {:else if activeId === 'network'}
    <NetworkSection />
  {:else if activeId === 'learning'}
    <LearningSection />
  {:else if activeId === 'gameday'}
    <GameDaySection />
  {/if}
  </SettingsLayout>
</main>

<style>
  .settings-workspace {
    min-width:0;max-width:1460px;margin:0 auto;padding:clamp(18px,3vw,42px) var(--hh-gutter) 44px;color:var(--hh-ink);
    --bg-primary:var(--hh-panel-deep);--bg-secondary:var(--hh-panel);--bg-card:var(--hh-card-background);
    --bg-card-hover:var(--hh-control-hover);--text-primary:var(--hh-ink);--text-secondary:var(--hh-muted);--text-muted:var(--hh-muted);
    --accent:var(--hh-accent);--border:var(--hh-line);--radius:var(--hh-radius-panel);--radius-sm:var(--hh-radius-control);
    --font-body:var(--hh-font);--font-display:var(--hh-display);
  }
  .workspace-head {display:grid;gap:8px;margin-bottom:24px;}
  .eyebrow {font-size:11px;font-weight:700;letter-spacing:.14em;color:var(--hh-accent);}
  h1 {font:500 clamp(36px,5vw,60px)/1.1 var(--hh-display);letter-spacing:-.04em;}
  .workspace-head p:not(.eyebrow) {font-size:14px;line-height:1.55;color:var(--hh-muted);}
  .settings-workspace :global(.settings-rail),.settings-workspace :global(.settings-section) {
    background:var(--hh-card-background);border:1px solid var(--hh-line);border-radius:var(--hh-radius-panel);
  }
  .settings-workspace :global(.rail-active) {background:var(--hh-control);border-color:var(--hh-line);color:var(--hh-accent);}
  .settings-workspace :global(.rail-item) {min-height:44px;}
  .settings-workspace :global(.section-icon) {background:var(--hh-control);color:var(--hh-accent);}
  .settings-workspace :global(.section-title) {font-family:var(--hh-display);letter-spacing:0;}
  .settings-workspace :global(.settings-btn.btn-primary) {background:var(--hh-accent);border-color:var(--hh-accent);color:#20241f;}
  .settings-workspace :global(.settings-btn.btn-primary:hover:not(:disabled)) {background:#f0dfbc;border-color:#f0dfbc;color:#20241f;}
  .settings-workspace :global(.rail-item:focus-visible),.settings-workspace :global(.settings-btn:focus-visible) {outline:3px solid var(--hh-focus);outline-offset:2px;}
  @media(max-width:1120px) {.settings-workspace :global(.settings-shell){grid-template-columns:minmax(0,1fr);gap:16px;}.settings-workspace :global(.settings-rail){position:static;max-height:none;}}
  @media(max-width:600px) {.settings-workspace{padding:18px 16px 32px;}.workspace-head{margin-bottom:16px;}}
  @media(prefers-reduced-motion:reduce) {.settings-workspace :global(.settings-main),.settings-workspace :global(.settings-section){animation:none;}}
</style>
