<script>
  import { page } from '$app/stores'
  import { sonos } from '$lib/stores/sonos.js'
  import { automation } from '$lib/stores/automation.js'

  const NAV = [
    { id: 'home', label: 'Home', href: '/' },
    { id: 'music', label: 'Music', href: '/music' },
    { id: 'settings', label: 'Settings', href: '/settings' },
  ]

  $: currentPath = $page.url.pathname
  $: playing = $sonos.state === 'PLAYING'
  $: track = $sonos.track || 'Nothing playing'
  $: artist = $sonos.artist || ''
  $: mode = $automation.mode
</script>

<aside class="sidebar">
  <div class="sidebar-brand">Home Hub</div>
  <nav class="sidebar-nav">
    {#each NAV as item}
      {@const active = currentPath === item.href || (item.href !== '/' && currentPath.startsWith(item.href))}
      <a
        href={item.href}
        class="sidebar-nav-item"
        class:sidebar-nav-item-active={active}
      >
        <span class="sidebar-nav-icon">
          {#if item.id === 'home'}
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8.5L10 3l7 5.5V17a1 1 0 0 1-1 1h-3v-6H7v6H4a1 1 0 0 1-1-1V8.5Z" /></svg>
          {:else if item.id === 'music'}
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M8 17.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5Z" /><path d="M10.5 15V3.5L17 2v11" /><path d="M17 13a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0Z" /></svg>
          {:else}
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="10" r="3" /><path d="M10 1.5v2M10 16.5v2M1.5 10h2M16.5 10h2M3.4 3.4l1.4 1.4M15.2 15.2l1.4 1.4M3.4 16.6l1.4-1.4M15.2 4.8l1.4-1.4" /></svg>
          {/if}
        </span>
        <span class="sidebar-nav-label">{item.label}</span>
      </a>
    {/each}
  </nav>

  <div class="sidebar-now-playing">
    <div class="sidebar-now-playing-label">{mode ? `Mode · ${mode}` : 'Mode'}</div>
    <div class="sidebar-now-playing-track" class:is-playing={playing}>{track}</div>
    {#if artist}
      <div class="sidebar-now-playing-artist">{artist}</div>
    {/if}
  </div>
</aside>

<style>
  /* Anchor reset so <a> looks like the React <button> did. */
  .sidebar-nav-item { text-decoration: none; }
</style>
