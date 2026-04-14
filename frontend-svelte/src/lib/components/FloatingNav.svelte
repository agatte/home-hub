<script>
  import { page } from '$app/stores'
  import { Home, Music, BarChart3, Settings } from 'lucide-svelte'

  const NAV = [
    { id: 'home', href: '/', label: 'Home', icon: Home },
    { id: 'music', href: '/music', label: 'Music', icon: Music },
    { id: 'analytics', href: '/analytics', label: 'Analytics', icon: BarChart3 },
    { id: 'settings', href: '/settings', label: 'Settings', icon: Settings },
  ]

  $: currentPath = $page.url.pathname

  function isActive(href, path) {
    if (href === '/') return path === '/'
    return path.startsWith(href)
  }
</script>

<nav class="floating-nav" aria-label="Main navigation">
  {#each NAV as item}
    <a
      href={item.href}
      class="floating-nav-item"
      class:active={isActive(item.href, currentPath)}
      aria-label={item.label}
      aria-current={isActive(item.href, currentPath) ? 'page' : undefined}
    >
      <svelte:component this={item.icon} size={20} strokeWidth={1.5} />
    </a>
  {/each}
</nav>

<style>
  .floating-nav {
    position: fixed;
    bottom: 20px;
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    gap: 4px;
    padding: 6px;
    background: rgba(10, 10, 15, 0.55);
    backdrop-filter: blur(16px) saturate(1.2);
    -webkit-backdrop-filter: blur(16px) saturate(1.2);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 999px;
    z-index: 50;
    transition: opacity 0.3s ease;
  }

  .floating-nav-item {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
    border-radius: 50%;
    color: var(--text-secondary);
    text-decoration: none;
    transition: color 0.2s, background 0.2s, transform 0.1s;
    cursor: pointer;
  }

  .floating-nav-item:hover {
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.06);
  }

  .floating-nav-item:active {
    transform: scale(0.93);
  }

  .floating-nav-item.active {
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.08);
  }

  @media (max-width: 480px) {
    .floating-nav {
      bottom: calc(8px + env(safe-area-inset-bottom, 0px));
      padding: 4px;
    }
    .floating-nav-item {
      width: 40px;
      height: 40px;
    }
  }
</style>
