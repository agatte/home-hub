<script>
  // #157: opt-in Settings archetype is a navigation-only directory.
  // All existing configuration stays on the functional /settings route.
  import { withQuietAtlasShell } from '$lib/quietAtlas/navigation.js'

  /** @type {string | null} */
  let expandedGroup = 'behavior'

  const GROUPS = [
    {
      id: 'behavior',
      index: '01',
      title: 'How HomeHub behaves',
      note: 'The rules and rhythms behind an otherwise quiet home.',
      items: [
        { id: 'automation', label: 'Automation', detail: 'Behavior and autonomy options' },
        { id: 'dnd', label: 'Do Not Disturb', detail: 'Temporary quiet periods' },
        { id: 'schedule', label: 'Schedule', detail: 'Routine timing and recurring plans' },
        { id: 'modes', label: 'Legacy modes', detail: 'Existing mode configuration · advanced' },
      ],
    },
    {
      id: 'experience',
      index: '02',
      title: 'Listening & experiences',
      note: 'Keep playback and preference tools accessible, without a permanent widget wall.',
      items: [
        { id: 'music', label: 'Music', detail: 'Current music preferences and integrations' },
        { id: 'audio', label: 'Audio', detail: 'Listening and sound options' },
        { id: 'learning', label: 'Learning', detail: 'Learning and feedback tools' },
        { id: 'gameday', label: 'Game Day', detail: 'Sports experience settings' },
      ],
    },
    {
      id: 'system',
      index: '03',
      title: 'Systems & access',
      note: 'The existing operational tools remain one deliberate step away.',
      items: [
        { id: 'overview', label: 'Settings overview', detail: 'Current system configuration' },
        { id: 'host', label: 'Host / Travel', detail: 'Host and travel options' },
        { id: 'network', label: 'Network', detail: 'Network and DNS controls' },
      ],
    },
  ]
</script>

<svelte:head>
  <title>Settings · Quiet Atlas design review | HomeHub</title>
  <meta name="description" content="Opt-in, navigation-only Settings directory for the Quiet Atlas redesign. Existing configuration stays functional." />
</svelte:head>

<main class="settings-review" aria-label="Quiet Atlas Settings design review">
  <div class="topline">
    <span class="identity">QUIET ATLAS <span aria-hidden="true">×</span> SETTINGS</span>
    <span class="review-label">DESIGN STUDY / NAVIGATION ONLY</span>
  </div>

  <header class="hero">
    <div class="hero-copy">
      <p class="eyebrow">A quieter way into the machinery</p>
      <h1><span class="desktop-heading">Keep the details <em>close, not loud.</em></span><span class="phone-heading">Settings, <em>made simple.</em></span></h1>
      <p class="intro">Find the existing HomeHub configuration by purpose. This page shows no live settings or device state and changes nothing itself.</p>
    </div>
    <div class="hero-aside" role="note">
      <span class="aside-kicker">CURRENT FUNCTIONAL SETTINGS</span>
      <p>Each destination opens an existing Settings section. Those pages still contain the actual controls and their normal behavior.</p>
      <a href={withQuietAtlasShell('/settings')} class="all-settings">Open all current settings <span aria-hidden="true">↗</span></a>
    </div>
  </header>

  <div class="groups">
    {#each GROUPS as group (group.id)}
      <section class="group" aria-labelledby={'settings-' + group.id}>
        <div class="section-lead">
          <span class="ordinal">{group.index} / CONFIGURATION</span>
          <h2 id={'settings-' + group.id}>{group.title}</h2>
          <p>{group.note}</p>
          <button
            class="mobile-group-toggle"
            type="button"
            aria-controls={'settings-links-' + group.id}
            aria-expanded={expandedGroup === group.id}
            on:click={() => expandedGroup = expandedGroup === group.id ? null : group.id}
          >
            <span class="mobile-group-copy"><strong>{group.title}</strong><small>{group.note}</small></span>
            <span class="mobile-group-indicator" aria-hidden="true">{expandedGroup === group.id ? '−' : '+'}</span>
          </button>
        </div>
        <nav
          id={'settings-links-' + group.id}
          class="section-links"
          class:mobile-collapsed={expandedGroup !== group.id}
          aria-label={group.title}
        >
          {#each group.items as item (item.id)}
            <a class="setting-link" href={withQuietAtlasShell('/settings?section=' + item.id)} aria-label={'Open current ' + item.label + ' settings'}>
              <span class="link-copy"><strong>{item.label}</strong><small>{item.detail}</small></span>
              <span class="link-icon" aria-hidden="true">↗</span>
            </a>
          {/each}
        </nav>
      </section>
    {/each}
  </div>

  <footer class="footer">
    <p>Preview navigation only. No preferences are read, inferred, saved, or changed on this page. The functional Settings screen remains available throughout the redesign.</p>
    <a href="/quiet-atlas/home">Return to Home <span aria-hidden="true">↗</span></a>
  </footer>
</main>

<style>
  .phone-heading,.mobile-group-toggle {display:none}
  .settings-review {--ink:#e8eee4;--muted:#a6b9aa;--line:rgba(198,222,199,.16);--gold:#dec69a;color:var(--ink);background:radial-gradient(ellipse at 80% -8%,rgba(143,157,103,.14),transparent 47%),#101b15;min-height:100%;padding:clamp(22px,3vw,42px) clamp(17px,4vw,56px) 56px;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
  .settings-review * {box-sizing:border-box}
  .settings-review a {color:inherit;text-decoration:none}
  .settings-review a:focus-visible {outline:3px solid #d5e7bd;outline-offset:3px}
  .topline {display:flex;justify-content:space-between;gap:15px;flex-wrap:wrap;align-items:center;color:var(--muted);font-size:10px;font-weight:700;letter-spacing:.15em;padding-bottom:20px;border-bottom:1px solid var(--line)}
  .identity {color:var(--gold)}
  .identity span {color:#98a79b;padding:0 5px}
  .review-label {font-size:9px}
  .hero {display:grid;grid-template-columns:minmax(0,1.5fr) minmax(250px,.7fr);gap:clamp(26px,5vw,80px);padding:clamp(48px,7vw,93px) 0 clamp(42px,6vw,78px);border-bottom:1px solid var(--line);align-items:end}
  .eyebrow,.aside-kicker,.ordinal {color:var(--gold);font-size:10px;font-weight:750;letter-spacing:.15em}
  .eyebrow {margin:0 0 21px}
  h1 {font-size:clamp(37px,5vw,69px);line-height:1.09;letter-spacing:-.055em;max-width:750px;font-weight:550;margin:0 0 25px}
  h1 em {font-family:Georgia,"Times New Roman",serif;font-weight:400;letter-spacing:-.035em}
  .intro {margin:0;color:var(--muted);max-width:560px;font-size:14px;line-height:1.8}
  .hero-aside {border-left:1px solid rgba(211,190,145,.34);padding-left:21px;max-width:370px}
  .hero-aside p {font-size:12px;color:var(--muted);line-height:1.75;margin:12px 0 20px}
  .all-settings {display:inline-flex;align-items:center;gap:14px;min-height:44px;font-size:12px;font-weight:700;border-bottom:1px solid rgba(222,198,154,.55)}
  .groups {max-width:1330px}
  .group {display:grid;grid-template-columns:minmax(180px,.65fr) minmax(0,1.35fr);gap:clamp(25px,5vw,75px);padding:clamp(27px,4vw,48px) 0;border-bottom:1px solid var(--line)}
  .section-lead {padding-top:4px}
  .section-lead h2 {font:400 clamp(24px,2.5vw,37px)/1.2 Georgia,"Times New Roman",serif;letter-spacing:-.03em;margin:14px 0 12px}
  .section-lead p {font-size:12px;line-height:1.7;color:var(--muted);max-width:310px;margin:0}
  .section-links {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px 24px}
  .setting-link {display:flex;align-items:center;justify-content:space-between;gap:10px;border-bottom:1px solid var(--line);min-height:79px;padding:14px 2px;min-width:0}
  .setting-link:hover {color:#e9d3a9;border-color:rgba(222,198,154,.5)}
  .link-copy {display:flex;flex-direction:column;gap:6px;min-width:0}
  .link-copy strong {font-size:14px;font-weight:600;line-height:1.3}
  .link-copy small {color:var(--muted);font-size:11px;line-height:1.45}
  .link-icon {font-size:15px;flex:0 0 auto;color:var(--gold)}
  .footer {display:flex;align-items:center;justify-content:space-between;gap:20px;margin-top:29px;font-size:11px;color:var(--muted);line-height:1.7}
  .footer p {max-width:710px;margin:0}
  .footer a {display:inline-flex;gap:12px;align-items:center;white-space:nowrap;min-height:44px;font-weight:600;color:var(--ink)}
  @media(max-width:900px){.hero{grid-template-columns:minmax(0,1fr);gap:24px}.hero-aside{max-width:none}.group{grid-template-columns:minmax(0,1fr);gap:22px}.section-lead p{max-width:560px}}
  @media(max-width:600px){
    .settings-review {padding:16px 16px calc(40px + env(safe-area-inset-bottom,0px));min-width:0}
    .topline {font-size:10px;gap:9px;line-height:1.4;padding-bottom:13px}
    .review-label {font-size:9px}
    .hero {padding:24px 0 22px;gap:17px}
    .eyebrow {margin-bottom:10px}
    .desktop-heading {display:none}
    .phone-heading {display:inline}
    h1 {font-size:clamp(31px,8vw,38px);line-height:1.13;margin-bottom:10px}
    .intro {font-size:13px;line-height:1.55}
    .hero-aside {padding:12px 14px;background:rgba(222,198,154,.045);border:1px solid var(--line);border-radius:14px}
    .hero-aside p {font-size:12px;line-height:1.5;margin:7px 0 10px}
    .aside-kicker {font-size:10px}
    .all-settings {box-sizing:border-box;display:flex;justify-content:space-between;min-height:48px;width:100%;font-size:13px}
    .group {display:block;padding:15px 0 14px;min-width:0}
    .section-lead {padding:0}
    .section-lead>h2,.section-lead>p {display:none}
    .ordinal {font-size:10px;letter-spacing:.12em}
    .mobile-group-toggle {display:flex;align-items:center;justify-content:space-between;gap:14px;width:100%;min-height:76px;margin-top:7px;padding:12px 14px;background:linear-gradient(110deg,rgba(143,164,117,.12),rgba(103,130,98,.05));border:1px solid var(--line);border-radius:14px;text-align:left;color:var(--ink);font:inherit;cursor:pointer}
    .mobile-group-copy {display:flex;flex-direction:column;gap:5px;min-width:0}
    .mobile-group-copy strong {font-size:16px;font-weight:650;line-height:1.25}
    .mobile-group-copy small {font-size:12px;color:var(--muted);line-height:1.45}
    .mobile-group-indicator {font-size:23px;color:var(--gold);flex:0 0 20px;text-align:center}
    .mobile-group-toggle:focus-visible {outline:3px solid #d5e7bd;outline-offset:3px}
    .section-links {grid-template-columns:minmax(0,1fr);gap:0;padding:4px 4px 0 11px}
    .section-links.mobile-collapsed {display:none}
    .setting-link {box-sizing:border-box;min-height:64px;padding:10px 5px}
    .link-copy strong {font-size:15px}
    .link-copy small {font-size:12px}
    .link-icon {font-size:19px}
    .footer {align-items:flex-start;flex-direction:column;margin-top:20px;gap:12px;font-size:12px}
    .footer a {font-size:13px}
  }
  @media(prefers-reduced-motion:reduce){.setting-link,.all-settings{scroll-behavior:auto}}
</style>
