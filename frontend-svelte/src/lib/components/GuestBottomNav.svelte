<script>
  import { page } from '$app/stores'
  import { Home, Wifi, Wine, Sprout, Sparkles } from 'lucide-svelte'

  const TABS = [
    { href: '/guest',        label: 'Welcome', icon: Home },
    { href: '/guest/wifi',   label: 'Wi-Fi',   icon: Wifi },
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
    position:fixed;z-index:50;bottom:0;left:50%;transform:translateX(-50%);
    width:min(100%,620px);display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:3px;
    padding:8px max(9px,env(safe-area-inset-right)) calc(8px + env(safe-area-inset-bottom)) max(9px,env(safe-area-inset-left));
    background:rgba(24,33,28,.97);border:1px solid rgba(229,220,197,.19);border-bottom:0;
    border-radius:20px 20px 0 0;box-shadow:0 -8px 30px rgba(0,0,0,.2);
    backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
  }
  .guest-nav-tab {
    display:flex;flex-direction:column;align-items:center;justify-content:center;min-width:0;
    gap:5px;min-height:54px;padding:5px 2px;color:var(--guest-muted,#c3c9bd);
    font-family:var(--font-body);font-size:11px;font-weight:550;text-decoration:none;border-radius:12px;
  }
  .guest-nav-tab:hover {color:var(--guest-ink,#f5f0e6);}
  .guest-nav-tab.active {color:var(--guest-gold,#e4c99e);background:#374137;font-weight:700;}
  .guest-nav-tab span {line-height:1.1;text-align:center;overflow-wrap:anywhere;}
  @media(min-width:760px) {.guest-nav {bottom:16px;border-radius:20px;border-bottom:1px solid rgba(229,220,197,.19);}}
</style>
