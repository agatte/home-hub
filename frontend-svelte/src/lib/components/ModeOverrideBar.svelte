<script>
  import { automation } from '$lib/stores/automation.js'
  import { setManualMode, setSocialStyle } from '$lib/stores/init.js'

  const MODES = [
    { id: 'gaming',   label: 'Gaming',   icon: '🎮' },
    { id: 'working',  label: 'Working',  icon: '💻' },
    { id: 'watching', label: 'Watching', icon: '🎬' },
    { id: 'movie',    label: 'Movie',    icon: '🍿' },
    { id: 'relax',    label: 'Relax',    icon: '🌙' },
    { id: 'social',   label: 'Party',    icon: '🎉' },
    { id: 'auto',     label: 'Auto',     icon: '✨' },
  ]

  const SOCIAL_STYLES = [
    { id: 'color_cycle',  label: 'Color Cycle', icon: '🌈' },
    { id: 'club',         label: 'Club',        icon: '💜' },
    { id: 'rave',         label: 'Rave',        icon: '⚡' },
    { id: 'fire_and_ice', label: 'Fire & Ice',  icon: '🔥' },
  ]

  $: currentMode = $automation.mode
  $: manualOverride = $automation.manual_override
  $: socialStyle = $automation.social_style
  $: showSocialStyles = currentMode === 'social'

  // Inline reactive map — Svelte's reactivity doesn't trace deps through
  // function calls in the template, so computing this as a reactive value
  // keeps the button highlights in sync when the store updates.
  $: activeMap = Object.fromEntries(
    MODES.map((m) => [
      m.id,
      m.id === 'auto' ? !manualOverride : manualOverride && currentMode === m.id,
    ])
  )
</script>

<div>
  <div class="mode-override-bar">
    {#each MODES as mode}
      <button
        class="mode-btn"
        class:mode-btn-active={activeMap[mode.id]}
        on:click={() => setManualMode(mode.id)}
      >
        <span class="mode-btn-icon">{mode.icon}</span>
        <span class="mode-btn-label">{mode.label}</span>
      </button>
    {/each}
  </div>
  {#if showSocialStyles}
    <div class="social-style-bar">
      {#each SOCIAL_STYLES as style}
        <button
          class="social-style-btn"
          class:social-style-btn-active={socialStyle === style.id}
          on:click={() => setSocialStyle(style.id)}
        >
          <span class="mode-btn-icon">{style.icon}</span>
          <span class="mode-btn-label">{style.label}</span>
        </button>
      {/each}
    </div>
  {/if}
</div>
