<script>
  import { onMount } from 'svelte'
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
  import OverviewSection from './sections/OverviewSection.svelte'
  import HostSection from './sections/HostSection.svelte'
  import AutomationSection from './sections/AutomationSection.svelte'
  import DndSection from './sections/DndSection.svelte'
  import ScheduleSection from './sections/ScheduleSection.svelte'
  import ModesSection from './sections/ModesSection.svelte'
  import MusicSection from './sections/MusicSection.svelte'
  import AudioSection from './sections/AudioSection.svelte'
  import NetworkSection from './sections/NetworkSection.svelte'
  import LearningSection from './sections/LearningSection.svelte'
  import GameDaySection from './sections/GameDaySection.svelte'

  const SECTIONS = [
    { id: 'overview',   label: 'Overview',          icon: Activity },
    { id: 'host',       label: 'Host / Travel',     icon: Laptop   },
    { id: 'automation', label: 'Automation',        icon: Sliders  },
    { id: 'dnd',        label: 'Do Not Disturb',    icon: Moon     },
    { id: 'schedule',   label: 'Schedule',          icon: Calendar },
    { id: 'modes',      label: 'Modes',             icon: Palette  },
    { id: 'music',      label: 'Music',             icon: Music    },
    { id: 'audio',      label: 'Audio',             icon: Volume2  },
    { id: 'network',    label: 'Network',           icon: Network  },
    { id: 'learning',   label: 'Learning',          icon: Brain    },
    { id: 'gameday',    label: 'Game Day',          icon: Trophy   },
  ]

  /** @type {string} */
  let activeId = 'overview'

  // Sync activeId from ?section=X on mount and whenever the URL changes.
  $: {
    const fromUrl = $page.url.searchParams.get('section')
    if (fromUrl && SECTIONS.some((s) => s.id === fromUrl)) {
      activeId = fromUrl
    }
  }

  onMount(() => {
    const fromUrl = $page.url.searchParams.get('section')
    if (fromUrl && SECTIONS.some((s) => s.id === fromUrl)) {
      activeId = fromUrl
    }
  })

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
  <title>Settings · Home Hub</title>
</svelte:head>

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
