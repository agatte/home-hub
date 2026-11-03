<script>
  import { onMount, tick } from 'svelte'
  import { page } from '$app/stores'
  import {
    Home, Sliders, Music, BarChart3, MoreHorizontal, X, ArrowUpRight,
    Settings, BookOpen, Brain, Building2, Trophy, Users,
  } from 'lucide-svelte'
  import { connected } from '$lib/stores/connection.js'
  import { MORE_DESTINATIONS, activeQuietAtlasSection, isQuietAtlasReadOnlyPreview, withQuietAtlasShell } from '$lib/quietAtlas/navigation.js'

  const NAV_ITEMS = [
    { id: 'home', label: 'Home', href: '/quiet-atlas/home', icon: Home },
    { id: 'control', label: 'Control', href: '/quiet-atlas/control', icon: Sliders },
    { id: 'music', label: 'Music', href: '/quiet-atlas/music', icon: Music },
    { id: 'insights', label: 'Insights', href: '/quiet-atlas/insights', icon: BarChart3 },
  ]

  const MORE_ICONS = {
    settings: Settings,
    journal: BookOpen,
    personality: Brain,
    apartment: Building2,
    gameday: Trophy,
    guest: Users,
  }

  $: activeSection = activeQuietAtlasSection($page.url.pathname)
  $: readOnlyPreview = isQuietAtlasReadOnlyPreview($page.url.pathname)
  $: destinations = MORE_DESTINATIONS.map((item) => ({
    ...item,
    href: item.shell ? withQuietAtlasShell(item.href) : item.href,
  }))

  let moreOpen = false
  let returnFocus = null
  let closeButton = null
  let panel = null

  /** @param {MouseEvent} event */
  async function openMore(event) {
    returnFocus = event.currentTarget
    moreOpen = true
    await tick()
    closeButton?.focus()
  }

  /** @param {boolean} [restoreFocus] */
  function closeMore(restoreFocus = true) {
    moreOpen = false
    if (restoreFocus) {
      tick().then(() => {
        if (returnFocus?.isConnected) returnFocus.focus()
      })
    }
  }

  // Any route transition, including browser Back/Forward, must dismiss More.
  // No restore-focus to a button on a route being replaced.
  onMount(() => {
    let previousRoute = null
    const unsubscribe = page.subscribe(({ url }) => {
      const route = url.pathname + url.search + url.hash
      if (previousRoute !== null && route !== previousRoute && moreOpen) closeMore(false)
      previousRoute = route
    })
    return unsubscribe
  })

  /** @param {KeyboardEvent} event */
  function handleKeydown(event) {
    if (!moreOpen) return
    if (event.key === 'Escape') {
      event.preventDefault()
      closeMore()
      return
    }
    if (event.key !== 'Tab' || !panel) return
    const focusable = [...panel.querySelectorAll('button:not(:disabled), a[href]')]
      .filter((element) => element instanceof HTMLElement)
    if (!focusable.length) {
      event.preventDefault()
      panel.focus()
      return
    }
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && (document.activeElement === last || !panel.contains(document.activeElement))) {
      event.preventDefault()
      first.focus()
    }
  }
</script>

<svelte:window on:keydown={handleKeydown} />

<div class="qa-shell">
  <aside class="qa-sidebar" aria-label="HomeHub navigation" inert={moreOpen}>
    <a class="qa-brand" href="/quiet-atlas/home" aria-label="HomeHub Quiet Atlas Home">
      <span class="qa-brand-mark" aria-hidden="true">H</span>
      <span class="qa-brand-copy"><strong>HomeHub</strong><small>Quiet Atlas</small></span>
    </a>

    <p class="qa-rail-kicker">APARTMENT CONTROL</p>
    <nav class="qa-desktop-nav" aria-label="Primary navigation">
      {#each NAV_ITEMS as item (item.id)}
        <a
          href={item.href}
          class:active={activeSection === item.id}
          aria-current={activeSection === item.id ? 'page' : undefined}
        >
          <svelte:component this={item.icon} size={19} strokeWidth={1.7} aria-hidden="true" />
          <span>{item.label}</span>
          {#if item.id === 'control'}<span class="qa-nav-hint">Lights</span>{/if}
        </a>
      {/each}
      <button
        type="button"
        class:active={activeSection === 'more' || moreOpen}
        aria-expanded={moreOpen}
        aria-controls="qa-more-panel"
        on:click={openMore}
      >
        <MoreHorizontal size={19} strokeWidth={1.7} aria-hidden="true" />
        <span>More</span>
        <span class="qa-nav-hint">Explore</span>
      </button>
    </nav>

    <div class="qa-sidebar-footer">
      <span class:online={$connected} class="qa-connection-dot" aria-hidden="true"></span>
      <span class="qa-sidebar-status">
        <strong>{$connected ? 'Connected' : 'Waiting for connection'}</strong>
        <small>{readOnlyPreview ? 'Read-only design preview' : 'Existing HomeHub tools · changes possible'}</small>
      </span>
    </div>
  </aside>

  <div class="qa-main" inert={moreOpen}>
    <header class="qa-mobile-header">
      <a class="qa-mobile-brand" href="/quiet-atlas/home" aria-label="HomeHub Quiet Atlas Home">
        <span class="qa-brand-mark" aria-hidden="true">H</span>
        <span><strong>HomeHub</strong><small>Quiet Atlas</small></span>
      </a>
      <span class="qa-preview-badge" class:functional={!readOnlyPreview}>{readOnlyPreview ? 'Read-only preview' : 'Functional HomeHub tools'}</span>
    </header>

    <div class="qa-shell-content">
      <slot />
    </div>
  </div>

  <nav class="qa-mobile-nav" aria-label="Primary navigation" inert={moreOpen}>
    {#each NAV_ITEMS as item (item.id)}
      <a
        href={item.href}
        class:active={activeSection === item.id}
        aria-current={activeSection === item.id ? 'page' : undefined}
      >
        <svelte:component this={item.icon} size={20} strokeWidth={1.7} aria-hidden="true" />
        <span>{item.label}</span>
      </a>
    {/each}
    <button
      type="button"
      class:active={activeSection === 'more' || moreOpen}
      aria-expanded={moreOpen}
      aria-controls="qa-more-panel"
      on:click={openMore}
    >
      <MoreHorizontal size={20} strokeWidth={1.7} aria-hidden="true" />
      <span>More</span>
    </button>
  </nav>

  {#if moreOpen}
    <button class="qa-more-scrim" type="button" aria-label="Close More destinations" on:click={() => closeMore()}></button>
    <section
      id="qa-more-panel"
      class="qa-more-panel"
      role="dialog"
      aria-modal="true"
      aria-labelledby="qa-more-title"
      tabindex="-1"
      bind:this={panel}
    >
      <header class="qa-more-header">
        <div>
          <p class="qa-more-kicker">DESTINATIONS</p>
          <h2 id="qa-more-title">More HomeHub</h2>
        </div>
        <button bind:this={closeButton} type="button" class="qa-close-more" aria-label="Close More destinations" on:click={() => closeMore()}>
          <X size={20} strokeWidth={1.8} aria-hidden="true" />
        </button>
      </header>
      <p class="qa-more-intro">Less-used tools stay one tap away without taking over the Home screen. Existing experiences remain available while their redesign is staged.</p>
      <div class="qa-more-list">
        {#each destinations as destination (destination.id)}
          <a class="qa-more-link" href={destination.href} on:click={() => closeMore(false)}>
            <span class="qa-more-icon">
              <svelte:component this={MORE_ICONS[destination.id]} size={19} strokeWidth={1.7} aria-hidden="true" />
            </span>
            <span class="qa-more-copy">
              <strong>{destination.label}</strong>
              <small>{destination.description}</small>
            </span>
            <ArrowUpRight size={17} strokeWidth={1.8} aria-hidden="true" />
          </a>
        {/each}
      </div>
      <p class="qa-more-note">The dedicated measured Apartment page remains a separate #192 workstream. This link preserves access to the current Apartment widget and household tools on legacy Home.</p>
    </section>
  {/if}
</div>

<style>
  .qa-shell {
    display: grid;
    grid-template-columns: 232px minmax(0, 1fr);
    min-height: 100dvh;
    color: #e9ece4;
    background: radial-gradient(ellipse at 70% 0%, rgba(93,126,94,.10), transparent 45%), #0f1914;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  .qa-sidebar {
    position: sticky;
    top: 0;
    height: 100dvh;
    display: flex;
    flex-direction: column;
    gap: 0;
    padding: 24px 16px 18px;
    border-right: 1px solid rgba(195,215,194,.12);
    background: rgba(10,19,14,.88);
    backdrop-filter: blur(18px);
  }
  .qa-brand, .qa-mobile-brand {
    display: flex;
    align-items: center;
    gap: 11px;
    color: #f0f0e8;
    text-decoration: none;
  }
  .qa-brand-mark {
    display: grid;
    place-items: center;
    flex: 0 0 38px;
    width: 38px;
    height: 38px;
    border: 1px solid #6c8a70;
    border-radius: 13px;
    color: #d7e5c9;
    background: linear-gradient(145deg, #314a37, #17271d);
    font-family: Georgia, serif;
    font-size: 22px;
  }
  .qa-brand-copy, .qa-mobile-brand > span:last-child {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .qa-brand-copy strong, .qa-mobile-brand strong { font-size: 16px; font-weight: 650; letter-spacing: -.02em; }
  .qa-brand-copy small, .qa-mobile-brand small { color: #9aafa0; font-size: 11px; letter-spacing: .08em; text-transform: uppercase; }
  .qa-rail-kicker { margin: 44px 10px 13px; color: #849b88; font-size: 10px; font-weight: 700; letter-spacing: .16em; }
  .qa-desktop-nav { display: flex; flex-direction: column; gap: 6px; }
  .qa-desktop-nav a, .qa-desktop-nav button {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 48px;
    width: 100%;
    padding: 0 12px;
    border: 1px solid transparent;
    border-radius: 13px;
    color: #aab9ad;
    background: transparent;
    text-decoration: none;
    text-align: left;
    font: inherit;
    font-size: 14px;
    cursor: pointer;
  }
  .qa-desktop-nav a:hover, .qa-desktop-nav button:hover { color: #f0f0e8; background: rgba(191,215,188,.06); }
  .qa-desktop-nav a.active, .qa-desktop-nav button.active {
    color: #e8f0df;
    border-color: rgba(166,194,160,.22);
    background: linear-gradient(110deg, rgba(98,133,99,.22), rgba(44,68,49,.13));
  }
  .qa-nav-hint { margin-left: auto; color: #839988; font-size: 10px; }
  .qa-sidebar-footer {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: auto;
    padding: 14px 10px 4px;
    border-top: 1px solid rgba(195,215,194,.10);
  }
  .qa-connection-dot { width: 8px; height: 8px; border-radius: 50%; flex: 0 0 8px; background: #8c9b8f; }
  .qa-connection-dot.online { background: #a6c99d; box-shadow: 0 0 12px rgba(166,201,157,.35); }
  .qa-sidebar-status { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  .qa-sidebar-status strong { color: #d6e0d3; font-size: 12px; font-weight: 600; }
  .qa-sidebar-status small { color: #849589; font-size: 10px; }
  .qa-main { min-width: 0; width: 100%; }
  .qa-shell-content { min-width: 0; width: 100%; max-width: 1600px; margin: 0 auto; }
  .qa-mobile-header, .qa-mobile-nav { display: none; }
  .qa-preview-badge { color: #e4d2a7; border: 1px solid rgba(199,169,106,.32); background: rgba(94,73,38,.22); border-radius: 999px; padding: 7px 10px; font-size: 10px; font-weight: 700; letter-spacing: .06em; white-space: nowrap; }
  .qa-preview-badge.functional { color: #d4e4d1; border-color: rgba(166,194,160,.34); background: rgba(70,102,78,.24); }
  .qa-mobile-nav a, .qa-mobile-nav button {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 5px;
    min-width: 0;
    min-height: 56px;
    padding: 6px 2px;
    border: 1px solid transparent;
    border-radius: 12px;
    color: #9eafa1;
    background: transparent;
    text-decoration: none;
    font: inherit;
    font-size: 10px;
    line-height: 1.1;
    cursor: pointer;
  }
  .qa-mobile-nav a.active, .qa-mobile-nav button.active { color: #e5efd9; background: rgba(128,166,123,.14); border-color: rgba(166,194,160,.18); }
  .qa-mobile-nav a:focus-visible, .qa-mobile-nav button:focus-visible,
  .qa-desktop-nav a:focus-visible, .qa-desktop-nav button:focus-visible,
  .qa-more-panel a:focus-visible, .qa-more-panel button:focus-visible,
  .qa-brand:focus-visible, .qa-mobile-brand:focus-visible { outline: 3px solid #d5e7bd; outline-offset: 3px; }
  /* Keep the page beneath the open More dialog stationary without mutable body styles. */
  :global(body:has(.qa-more-panel)) { overflow: hidden; }
  .qa-more-scrim { position: fixed; inset: 0; z-index: 600; border: 0; background: rgba(3,8,5,.72); backdrop-filter: blur(7px); }
  .qa-more-panel {
    position: fixed;
    z-index: 601;
    top: 24px;
    right: 24px;
    bottom: 24px;
    width: min(460px, calc(100vw - 48px));
    overflow-y: auto;
    overscroll-behavior: contain;
    padding: 24px;
    border: 1px solid rgba(190,215,188,.2);
    border-radius: 24px;
    color: #e9ece4;
    background: #142019;
    box-shadow: 0 24px 80px rgba(0,0,0,.42);
  }
  .qa-more-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
  .qa-more-kicker { color: #9fb59f; font-size: 10px; font-weight: 700; letter-spacing: .16em; }
  .qa-more-header h2 { margin-top: 8px; color: #f0f0e8; font-family: Georgia, serif; font-size: 30px; font-weight: 400; }
  .qa-close-more { display: grid; place-items: center; width: 44px; height: 44px; border: 1px solid rgba(190,215,188,.2); border-radius: 12px; color: #d5e3d2; background: rgba(190,215,188,.06); cursor: pointer; }
  .qa-more-intro { margin: 16px 0 20px; color: #b1c0b3; font-size: 13px; line-height: 1.6; }
  .qa-more-list { display: flex; flex-direction: column; gap: 8px; }
  .qa-more-link { display: grid; grid-template-columns: 40px minmax(0,1fr) 18px; align-items: center; gap: 12px; min-height: 64px; padding: 10px 11px; border: 1px solid rgba(190,215,188,.1); border-radius: 14px; color: inherit; background: rgba(190,215,188,.035); text-decoration: none; }
  .qa-more-link:hover { border-color: rgba(190,215,188,.28); background: rgba(190,215,188,.07); }
  .qa-more-icon { display: grid; place-items: center; width: 38px; height: 38px; border-radius: 11px; color: #c5d9bd; background: rgba(111,150,108,.16); }
  .qa-more-copy { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  .qa-more-copy strong { font-size: 13px; font-weight: 650; }
  .qa-more-copy small { color: #9eafa1; font-size: 11px; line-height: 1.45; }
  .qa-more-link > :last-child { color: #9fb59f; }
  .qa-more-note { margin-top: 18px; padding-top: 14px; border-top: 1px solid rgba(190,215,188,.1); color: #91a294; font-size: 11px; line-height: 1.55; }
  @media (max-width: 760px) {
    .qa-shell { display: flex; flex-direction: column; min-height: 100dvh; }
    .qa-sidebar { display: none; }
    .qa-main { flex: 1 0 auto; }
    .qa-mobile-header {
      position: sticky;
      top: 0;
      z-index: 100;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      min-height: 66px;
      padding: 10px 16px;
      border-bottom: 1px solid rgba(195,215,194,.10);
      background: rgba(13,23,17,.9);
      backdrop-filter: blur(18px);
    }
    .qa-mobile-brand { gap: 9px; }
    .qa-mobile-brand .qa-brand-mark { flex-basis: 34px; width: 34px; height: 34px; border-radius: 11px; font-size: 19px; }
    .qa-mobile-brand strong { font-size: 14px; }
    .qa-mobile-brand small { font-size: 9px; }
    .qa-shell-content { padding-bottom: calc(80px + env(safe-area-inset-bottom, 0px)); }
    .qa-mobile-nav {
      position: fixed;
      z-index: 500;
      left: 0;
      right: 0;
      bottom: 0;
      display: grid;
      grid-template-columns: repeat(5, minmax(0,1fr));
      gap: 2px;
      padding: 5px 8px calc(5px + env(safe-area-inset-bottom, 0px));
      border-top: 1px solid rgba(195,215,194,.13);
      background: rgba(10,19,14,.93);
      backdrop-filter: blur(22px) saturate(1.1);
    }
    .qa-more-panel {
      top: auto;
      right: 0;
      bottom: 0;
      left: 0;
      width: 100%;
      max-height: min(82dvh, 720px);
      padding: 22px 18px calc(20px + env(safe-area-inset-bottom, 0px));
      border-radius: 24px 24px 0 0;
      border-bottom: 0;
    }
    .qa-more-intro { font-size: 12px; }
    .qa-more-link { min-height: 66px; }
  }
  /* Preview-only Daylight coordination. Scoped to the opted-in Home page:
     no global theme, route persistence, or change to legacy/product surfaces. */
  :global(.qa-shell:has(.home-review.daylight)) {
    color: #263a2d;
    background: radial-gradient(ellipse at 68% 0%, rgba(176,151,103,.12), transparent 46%), #eeeee6;
  }
  :global(.qa-shell:has(.home-review.daylight)) .qa-sidebar {
    border-right-color: rgba(58,87,63,.17);
    background: rgba(245,245,236,.94);
  }
  :global(.qa-shell:has(.home-review.daylight)) .qa-brand,
  :global(.qa-shell:has(.home-review.daylight)) .qa-mobile-brand { color: #263a2d; }
  :global(.qa-shell:has(.home-review.daylight)) .qa-brand-mark {
    color: #38543b; background: linear-gradient(145deg,#e4e9dd,#d4dfd0); border-color: #9cb49d;
  }
  :global(.qa-shell:has(.home-review.daylight)) .qa-brand-copy small,
  :global(.qa-shell:has(.home-review.daylight)) .qa-mobile-brand small,
  :global(.qa-shell:has(.home-review.daylight)) .qa-rail-kicker,
  :global(.qa-shell:has(.home-review.daylight)) .qa-nav-hint { color: #5b705e; }
  :global(.qa-shell:has(.home-review.daylight)) .qa-desktop-nav a,
  :global(.qa-shell:has(.home-review.daylight)) .qa-desktop-nav button,
  :global(.qa-shell:has(.home-review.daylight)) .qa-mobile-nav a,
  :global(.qa-shell:has(.home-review.daylight)) .qa-mobile-nav button { color: #536b59; }
  :global(.qa-shell:has(.home-review.daylight)) .qa-desktop-nav a:hover,
  :global(.qa-shell:has(.home-review.daylight)) .qa-desktop-nav button:hover {
    color: #263a2d; background: rgba(83,121,80,.09);
  }
  :global(.qa-shell:has(.home-review.daylight)) .qa-desktop-nav a.active,
  :global(.qa-shell:has(.home-review.daylight)) .qa-desktop-nav button.active,
  :global(.qa-shell:has(.home-review.daylight)) .qa-mobile-nav a.active,
  :global(.qa-shell:has(.home-review.daylight)) .qa-mobile-nav button.active {
    color: #25452b;
    background: rgba(91,135,88,.16);
    border-color: rgba(61,104,65,.25);
  }
  :global(.qa-shell:has(.home-review.daylight)) .qa-sidebar-footer {
    border-top-color: rgba(58,87,63,.15);
  }
  :global(.qa-shell:has(.home-review.daylight)) .qa-sidebar-status strong { color: #304b36; }
  :global(.qa-shell:has(.home-review.daylight)) .qa-sidebar-status small { color: #627564; }
  :global(.qa-shell:has(.home-review.daylight)) .qa-connection-dot { background: #879a88; }
  :global(.qa-shell:has(.home-review.daylight)) .qa-connection-dot.online {
    background: #4e8757; box-shadow: 0 0 10px rgba(78,135,87,.2);
  }
  :global(.qa-shell:has(.home-review.daylight)) .qa-preview-badge {
    color: #76562c; background: #f3e7cb; border-color: rgba(133,98,46,.35);
  }
  :global(.qa-shell:has(.home-review.daylight)) .qa-mobile-header {
    border-bottom-color: rgba(58,87,63,.17);
    background: rgba(244,245,234,.95);
  }
  :global(.qa-shell:has(.home-review.daylight)) .qa-mobile-nav {
    border-top-color: rgba(58,87,63,.2);
    background: rgba(244,245,234,.97);
  }
  :global(.qa-shell:has(.home-review.daylight)) .qa-more-panel {
    color: #263a2d; background: #f5f5ec; border-color: rgba(58,87,63,.25);
  }
  :global(.qa-shell:has(.home-review.daylight)) .qa-more-kicker,
  :global(.qa-shell:has(.home-review.daylight)) .qa-more-link > :last-child { color: #5a795c; }
  :global(.qa-shell:has(.home-review.daylight)) .qa-more-header h2 { color: #263a2d; }
  :global(.qa-shell:has(.home-review.daylight)) .qa-more-intro,
  :global(.qa-shell:has(.home-review.daylight)) .qa-more-copy small,
  :global(.qa-shell:has(.home-review.daylight)) .qa-more-note { color: #556c5b; }
  :global(.qa-shell:has(.home-review.daylight)) .qa-more-link {
    border-color: rgba(58,87,63,.16); background: rgba(99,134,91,.07);
  }
  :global(.qa-shell:has(.home-review.daylight)) .qa-more-link:hover {
    border-color: rgba(58,87,63,.32); background: rgba(99,134,91,.12);
  }
  :global(.qa-shell:has(.home-review.daylight)) .qa-more-icon {
    color: #32543a; background: rgba(99,134,91,.16);
  }
  :global(.qa-shell:has(.home-review.daylight)) .qa-close-more {
    color: #32543a; border-color: rgba(58,87,63,.25); background: rgba(99,134,91,.1);
  }
  :global(.qa-shell:has(.home-review.daylight)) .qa-more-note { border-top-color: rgba(58,87,63,.16); }
  :global(.qa-shell:has(.home-review.daylight)) .qa-mobile-nav a:focus-visible,
  :global(.qa-shell:has(.home-review.daylight)) .qa-mobile-nav button:focus-visible,
  :global(.qa-shell:has(.home-review.daylight)) .qa-desktop-nav a:focus-visible,
  :global(.qa-shell:has(.home-review.daylight)) .qa-desktop-nav button:focus-visible,
  :global(.qa-shell:has(.home-review.daylight)) .qa-more-panel a:focus-visible,
  :global(.qa-shell:has(.home-review.daylight)) .qa-more-panel button:focus-visible,
  :global(.qa-shell:has(.home-review.daylight)) .qa-brand:focus-visible,
  :global(.qa-shell:has(.home-review.daylight)) .qa-mobile-brand:focus-visible {
    outline-color: #845e2e;
  }
  @media (prefers-reduced-motion: reduce) {
    .qa-desktop-nav a, .qa-desktop-nav button, .qa-mobile-nav a, .qa-mobile-nav button,
    .qa-more-link { transition: none; }
  }
</style>
