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
    { id: 'overview',   label: 'Overview',          icon: Activity, group: 'Systems & access', hint: 'Connections & diagnostics' },
    { id: 'host',       label: 'Host / Travel',     icon: Laptop, group: 'Systems & access', hint: 'Host mode & travel' },
    { id: 'automation', label: 'Automation',        icon: Sliders, group: 'How HomeHub behaves', hint: 'Detection & camera preferences' },
    { id: 'dnd',        label: 'Do Not Disturb',    icon: Moon, group: 'How HomeHub behaves', hint: 'Pause automatic changes' },
    { id: 'schedule',   label: 'Schedule',          icon: Calendar, group: 'How HomeHub behaves', hint: 'Daily timing & routines' },
    { id: 'modes',      label: 'Modes',             icon: Palette, group: 'How HomeHub behaves', hint: 'Light, volume & scene preferences' },
    { id: 'music',      label: 'Music',             icon: Music, group: 'Listening & experiences', hint: 'Playback preferences' },
    { id: 'audio',      label: 'Audio',             icon: Volume2, group: 'Listening & experiences', hint: 'Speaker & ambient audio' },
    { id: 'network',    label: 'Network',           icon: Network, group: 'Systems & access', hint: 'Network & DNS' },
    { id: 'learning',   label: 'Learning',          icon: Brain, group: 'Listening & experiences', hint: 'Learned preferences' },
    { id: 'gameday',    label: 'Game Day',          icon: Trophy, group: 'Listening & experiences', hint: 'Game Day preferences' },
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
    <p class="eyebrow">YOUR HOME · PREFERENCES</p>
    <h1>Settings</h1>
    <p>Make HomeHub work the way you want.</p>
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
  .settings-workspace :global(.settings-section) {background:transparent;border:0;box-shadow:none;backdrop-filter:none;padding:6px 0 24px;gap:22px;}
  .settings-workspace :global(.section-head) {align-items:center;padding-bottom:18px;gap:13px;}
  .settings-workspace :global(.section-title) {font-size:clamp(23px,3vw,32px);line-height:1.2;}
  .settings-workspace :global(.section-description) {font-size:14px;}
  .settings-workspace :global(.section-body.flush) {margin:0;}
  .settings-workspace :global(.group-title) {font-size:14px;letter-spacing:0;text-transform:none;color:var(--hh-ink);}
  .settings-workspace :global(.group-hint) {font-size:13px;}
  .settings-workspace :global(.setting-group) {gap:10px;}
  .settings-workspace :global(.row-label) {font-weight:550;}
  .settings-workspace :global(.row-hint) {overflow-wrap:anywhere;}
  .settings-workspace :global(.settings-main) {padding:2px 0 0;}
  .settings-workspace :global(.mode-summary) {white-space:normal;overflow-wrap:anywhere;min-width:0;}
  .settings-workspace :global(.mode-head) {flex-wrap:wrap;min-height:56px;}
  .settings-workspace :global(.mode-head:focus-visible) {outline:3px solid var(--hh-focus);outline-offset:-4px;}
  .settings-workspace :global(.section-icon) {background:var(--hh-control);color:var(--hh-accent);}
  .settings-workspace :global(.section-title) {font-family:var(--hh-display);letter-spacing:0;}
  .settings-workspace :global(.settings-btn.btn-primary) {background:var(--hh-accent);border-color:var(--hh-accent);color:#20241f;}
  .settings-workspace :global(.settings-btn.btn-primary:hover:not(:disabled)) {background:#f0dfbc;border-color:#f0dfbc;color:#20241f;}
  .settings-workspace :global(.rail-item:focus-visible),.settings-workspace :global(.settings-btn:focus-visible) {outline:3px solid var(--hh-focus);outline-offset:2px;}
  @media(max-width:1120px) {.settings-workspace :global(.settings-shell){grid-template-columns:minmax(0,1fr);gap:22px;}}
  @media(max-width:600px) {.settings-workspace{padding:18px 16px 32px;}.workspace-head{margin-bottom:18px;}.settings-workspace :global(.section-head){gap:10px;}.settings-workspace :global(.section-description){font-size:13px;}.settings-workspace :global(.mode-summary){flex-basis:100%;margin-left:40px;}.settings-workspace :global(.mode-chevron){margin-left:auto;}}
  @media(prefers-reduced-motion:reduce) {.settings-workspace :global(.settings-main),.settings-workspace :global(.settings-section){animation:none;}}
</style>
