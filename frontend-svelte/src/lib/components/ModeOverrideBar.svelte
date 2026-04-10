<script>
  import { automation } from '$lib/stores/automation.js'
  import { setManualMode, setSocialStyle } from '$lib/stores/init.js'
  import { MODE_CONFIG, modeColor } from '$lib/theme.js'
  import { Gamepad2, Monitor, Tv, Clapperboard, Flame, PartyPopper, Sparkles } from 'lucide-svelte'

  const MODES = [
    { id: 'gaming',   label: 'Gaming',   icon: Gamepad2 },
    { id: 'working',  label: 'Working',  icon: Monitor },
    { id: 'watching', label: 'Watching', icon: Tv },
    { id: 'movie',    label: 'Movie',    icon: Clapperboard },
    { id: 'relax',    label: 'Relax',    icon: Flame },
    { id: 'social',   label: 'Party',    icon: PartyPopper },
    { id: 'auto',     label: 'Auto',     icon: Sparkles },
  ]

  const SOCIAL_STYLES = [
    { id: 'color_cycle',  label: 'Cycle' },
    { id: 'club',         label: 'Club' },
    { id: 'rave',         label: 'Rave' },
    { id: 'fire_and_ice', label: 'Fire & Ice' },
  ]

  $: currentMode = $automation.mode
  $: manualOverride = $automation.manual_override
  $: socialStyle = $automation.social_style
  $: showSocialStyles = currentMode === 'social'

  $: activeMap = Object.fromEntries(
    MODES.map((m) => [
      m.id,
      m.id === 'auto' ? !manualOverride : manualOverride && currentMode === m.id,
    ])
  )
</script>

<div class="mode-override-pills">
  {#each MODES as mode}
    {@const isActive = activeMap[mode.id]}
    {@const color = modeColor(mode.id)}
    <button
      class="mode-pill"
      class:mode-pill-active={isActive}
      style={isActive ? `background: ${color}22; border-color: ${color}44; color: ${color}` : ''}
      on:click={() => setManualMode(mode.id)}
      title={mode.label}
      aria-label={mode.label}
    >
      <svelte:component this={mode.icon} size={16} strokeWidth={1.5} />
    </button>
  {/each}
</div>

{#if showSocialStyles}
  <div class="social-pills">
    {#each SOCIAL_STYLES as style}
      <button
        class="social-pill"
        class:social-pill-active={socialStyle === style.id}
        on:click={() => setSocialStyle(style.id)}
      >
        {style.label}
      </button>
    {/each}
  </div>
{/if}

<style>
  .mode-override-pills {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }

  .mode-pill {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-secondary);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.2s;
  }

  .mode-pill:hover {
    border-color: var(--border-hover);
    color: var(--text-primary);
  }

  .social-pills {
    display: flex;
    gap: 6px;
    margin-top: 10px;
    flex-wrap: wrap;
  }

  .social-pill {
    padding: 4px 12px;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-secondary);
    font-family: var(--font-body);
    font-size: 12px;
    cursor: pointer;
    transition: all 0.2s;
  }

  .social-pill:hover {
    border-color: var(--border-hover);
    color: var(--text-primary);
  }

  .social-pill-active {
    background: rgba(244, 114, 182, 0.15);
    border-color: rgba(244, 114, 182, 0.3);
    color: #f472b6;
  }
</style>
