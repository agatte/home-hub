<script>
  import { page } from '$app/stores'
  import { Home, Wifi, Wine, Sprout, Sparkles } from 'lucide-svelte'

  const TABS = [
    { href: '/guest',        label: 'Home',   icon: Home },
    { href: '/guest/wifi',   label: 'WiFi',   icon: Wifi },
    { href: '/guest/bar',    label: 'Bar',    icon: Wine },
    { href: '/guest/plants', label: 'Plants', icon: Sprout },
    { href: '/guest/vibe',   label: 'Vibe',   icon: Sparkles },
  ]

  $: pathname = $page.url.pathname
  // Exact match for /guest, prefix match for sub-routes. The pathname
  // arg is explicit (not closed over) so Svelte can see the dependency
  // and re-evaluate the class:active expression on client-side nav.
  function isActive(href, currentPath) {
    if (href === '/guest') {
      return currentPath === '/guest' || currentPath === '/guest/'
    }
    return currentPath === href || currentPath.startsWith(href + '/')
  }
</script>

<nav class="guest-nav" aria-label="Guest navigation">
  {#each TABS as tab}
    <a
      class="guest-nav-tab"
      class:active={isActive(tab.href, pathname)}
      href={tab.href}
      aria-current={isActive(tab.href, pathname) ? 'page' : undefined}
    >
      <svelte:component this={tab.icon} size={22} strokeWidth={1.5} />
      <span>{tab.label}</span>
    </a>
  {/each}
</nav>

<style>
  .guest-nav {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 50;
    display: flex;
    justify-content: space-around;
    align-items: stretch;
    padding: 8px 8px calc(8px + env(safe-area-inset-bottom));
    background: rgba(13, 13, 18, 0.85);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    border-top: 1px solid rgba(255, 255, 255, 0.08);
  }

  .guest-nav-tab {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 4px;
    min-height: 56px;
    padding: 6px 4px;
    color: rgba(245, 243, 238, 0.55);
    font-family: var(--font-body);
    font-size: 11px;
    text-decoration: none;
    border-radius: 12px;
    transition: color 0.15s, background 0.15s;
  }

  .guest-nav-tab:hover {
    color: rgba(245, 243, 238, 0.85);
  }

  .guest-nav-tab.active {
    color: #fff;
    background: rgba(255, 255, 255, 0.06);
  }

  .guest-nav-tab span {
    line-height: 1;
    letter-spacing: 0.02em;
  }
</style>
