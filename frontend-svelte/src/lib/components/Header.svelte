<script>
  import { page } from '$app/stores'
  import { connected, deviceStatus } from '$lib/stores/connection.js'
  import StatusDot from './StatusDot.svelte'

  $: currentPath = $page.url.pathname
  $: isMusic = currentPath.startsWith('/music')
  $: isSettings = currentPath.startsWith('/settings')
</script>

<header class="app-header">
  <a href="/" class="app-title">Home Hub</a>
  <div class="header-right">
    <div class="status-bar">
      <StatusDot active={$connected} label="Server" />
      <StatusDot active={$deviceStatus.hue} label="Hue" />
      <StatusDot active={$deviceStatus.sonos} label="Sonos" />
    </div>
    <a href={isMusic ? '/' : '/music'} class="settings-btn" class:settings-btn-active={isMusic} aria-label="Music">
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M8 17.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5Z" /><path d="M10.5 15V3.5L17 2v11" /><path d="M17 13a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0Z" /></svg>
    </a>
    <a href={isSettings ? '/' : '/settings'} class="settings-btn" class:settings-btn-active={isSettings} aria-label="Settings">
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="10" r="3" /><path d="M10 1.5v2M10 16.5v2M1.5 10h2M16.5 10h2M3.4 3.4l1.4 1.4M15.2 15.2l1.4 1.4M3.4 16.6l1.4-1.4M15.2 4.8l1.4-1.4" /></svg>
    </a>
  </div>
</header>

<style>
  .app-title { text-decoration: none; cursor: pointer; }
  .settings-btn { text-decoration: none; }
</style>
