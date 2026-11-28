<script>
  import { Home, Sliders, Music, BarChart3, Settings, Trophy } from 'lucide-svelte'
  const destinations = [
    { label: 'Home', href: '/', icon: Home },
    { label: 'Control', href: '/quiet-atlas/control', icon: Sliders },
    { label: 'Music', href: '/quiet-atlas/music', icon: Music },
    { label: 'Insights', href: '/quiet-atlas/insights', icon: BarChart3 },
    { label: 'Settings', href: '/quiet-atlas/settings', icon: Settings },
    { label: 'Game Day', href: '/gameday', icon: Trophy },
  ]
</script>

<nav class="stadium-navigation" aria-label="Game Day navigation">
  {#each destinations as destination}
    <a href={destination.href} class:active={destination.href === '/gameday'}
      aria-current={destination.href === '/gameday' ? 'page' : undefined}>
      <svelte:component this={destination.icon} size={19} strokeWidth={1.7} aria-hidden="true" />
      <span>{destination.label}</span>
    </a>
  {/each}
</nav>

<style>
  .stadium-navigation {
    position:fixed;z-index:50;top:calc(12px + env(safe-area-inset-top,0px));left:50%;transform:translateX(-50%);
    width:min(calc(100% - 20px),660px);display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:3px;
    padding:5px;border:1px solid rgba(169,200,235,.25);border-radius:17px;
    background:rgba(8,18,34,.94);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
    box-shadow:0 6px 28px rgba(0,0,0,.32);font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  }
  a {display:flex;align-items:center;justify-content:center;gap:6px;min-height:44px;min-width:0;border-radius:11px;
    color:#c3d1e2;text-decoration:none;font-size:12px;font-weight:600;white-space:nowrap;}
  a.active {background:#214873;color:#eaf4ff;box-shadow:inset 0 0 0 1px rgba(132,191,255,.23);}
  a:hover {background:#243952;color:#fff;}
  a:focus-visible {outline:2px solid #b5d9ff;outline-offset:2px;}
  @media(max-width:640px) {
    .stadium-navigation {top:calc(8px + env(safe-area-inset-top,0px));width:calc(100% - 12px);gap:2px;padding:4px;}
    a {flex-direction:column;gap:4px;min-height:50px;font-size:10px;letter-spacing:-.025em;}
  }
</style>
