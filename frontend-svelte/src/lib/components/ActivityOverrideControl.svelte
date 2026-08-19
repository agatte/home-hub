<script>
  import {
    Bot,
    ChevronDown,
    ChefHat,
    Flame,
    Gamepad2,
    Monitor,
    Moon,
    PartyPopper,
    Power,
    Tv,
  } from 'lucide-svelte'
  import { automation, activityLabel } from '$lib/stores/automation.js'
  import { setManualMode } from '$lib/stores/init.js'
  import { apiPost } from '$lib/api.js'
  import { modeColor } from '$lib/theme.js'

  const OVERRIDES = [
    { id: 'gaming', label: 'Gaming', icon: Gamepad2 },
    { id: 'working', label: 'Working', icon: Monitor },
    { id: 'watching', label: 'Watching', icon: Tv },
    { id: 'cooking', label: 'Cooking', icon: ChefHat },
    { id: 'relax', label: 'Relax', icon: Flame },
    { id: 'social', label: 'Social', icon: PartyPopper },
    { id: 'sleeping', label: 'Sleep', icon: Moon },
  ]

  let expanded = false
  let pending = null

  $: isAuto = !$automation.manual_override
  $: detectedActivity = activityLabel($automation.activity)
  $: manualLabel = OVERRIDES.find((item) => item.id === $automation.mode)?.label || 'Manual'
  $: summary = isAuto
    ? `Auto${detectedActivity ? ` · ${detectedActivity}` : ''}`
    : `Manual · ${manualLabel}`

  async function chooseMode(mode) {
    pending = mode
    try {
      await setManualMode(mode)
      if (mode !== 'auto') expanded = false
    } finally {
      pending = null
    }
  }

  async function allOff() {
    pending = 'alloff'
    try {
      await apiPost('/api/lights/all', { on: false })
    } finally {
      pending = null
    }
  }
</script>

<section class="activity-control" aria-label="Automation controls">
  <div class="control-summary">
    <div class="control-copy">
      <span class="control-eyebrow">Automation</span>
      <strong>{summary}</strong>
      <span class="control-helper">
        {isAuto
          ? 'HomeHub is choosing activity from current context.'
          : 'A manual activity override is active.'}
      </span>
    </div>

    <div class="control-actions">
      {#if !isAuto}
        <button
          class="control-button control-button-auto"
          disabled={pending !== null}
          on:click={() => chooseMode('auto')}
        >
          <Bot size={17} strokeWidth={1.6} aria-hidden="true" />
          <span>{pending === 'auto' ? 'Returning…' : 'Return to Auto'}</span>
        </button>
      {/if}

      <button
        class="control-button control-button-change"
        aria-expanded={expanded}
        aria-controls="activity-override-options"
        on:click={() => { expanded = !expanded }}
      >
        <span>{expanded ? 'Done' : 'Change'}</span>
        <ChevronDown
          size={17}
          strokeWidth={1.7}
          aria-hidden="true"
          class={expanded ? 'chevron-open' : ''}
        />
      </button>

      <button
        class="control-button control-button-danger"
        disabled={pending !== null}
        on:click={allOff}
      >
        <Power size={17} strokeWidth={1.6} aria-hidden="true" />
        <span>{pending === 'alloff' ? 'Turning off…' : 'All Off'}</span>
      </button>
    </div>
  </div>

  {#if expanded}
    <div class="override-panel" id="activity-override-options">
      <button
        class="override-option override-option-auto"
        class:active={isAuto}
        aria-pressed={isAuto}
        disabled={pending !== null}
        on:click={() => chooseMode('auto')}
      >
        <Bot size={20} strokeWidth={1.6} aria-hidden="true" />
        <span class="override-label">Auto</span>
        <span class="override-note">Use context</span>
      </button>

      {#each OVERRIDES as item (item.id)}
        {@const active = !isAuto && $automation.mode === item.id}
        {@const color = modeColor(item.id)}
        <button
          class="override-option"
          class:active
          aria-pressed={active}
          disabled={pending !== null}
          style="--option-accent: {color}"
          on:click={() => chooseMode(item.id)}
        >
          <svelte:component this={item.icon} size={20} strokeWidth={1.6} aria-hidden="true" />
          <span class="override-label">{item.label}</span>
          <span class="override-note">{item.id === 'sleeping' ? 'House sleep' : 'Manual override'}</span>
        </button>
      {/each}
    </div>
  {/if}
</section>

<style>
  .activity-control {
    margin-bottom: 18px;
    border: 1px solid var(--border);
    border-radius: 16px;
    background: rgba(10, 10, 15, 0.56);
    backdrop-filter: blur(14px) saturate(1.1);
    -webkit-backdrop-filter: blur(14px) saturate(1.1);
    overflow: hidden;
  }

  .control-summary {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 22px;
    padding: 16px 18px;
  }

  .control-copy {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .control-eyebrow {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--text-muted);
  }

  .control-copy strong {
    font-size: 15px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .control-helper {
    margin-top: 1px;
    font-size: 11px;
    color: var(--text-muted);
  }

  .control-actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;
    flex-wrap: wrap;
  }

  .control-button {
    min-height: 38px;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 8px 11px;
    background: rgba(255, 255, 255, 0.035);
    color: var(--text-secondary);
    font: inherit;
    font-size: 12px;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 7px;
  }

  .control-button:hover {
    border-color: var(--border-hover);
    background: rgba(255, 255, 255, 0.06);
    color: var(--text-primary);
  }

  .control-button:focus-visible,
  .override-option:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }

  .control-button:disabled,
  .override-option:disabled {
    opacity: 0.55;
    cursor: default;
  }

  .control-button-auto {
    color: var(--accent);
    border-color: color-mix(in srgb, var(--accent) 28%, var(--border));
  }

  .control-button-danger {
    color: #fca5a5;
    border-color: rgba(248, 113, 113, 0.15);
  }

  .control-button-danger:hover {
    border-color: rgba(248, 113, 113, 0.3);
    background: rgba(248, 113, 113, 0.06);
    color: #fecaca;
  }

  .control-button-change :global(.chevron-open) {
    transform: rotate(180deg);
  }

  .control-button-change :global(svg) {
    transition: transform 0.18s ease;
  }

  .override-panel {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 8px;
    padding: 0 18px 18px;
    animation: panelIn 0.18s ease-out both;
  }

  .override-option {
    --option-accent: var(--accent);
    min-width: 0;
    min-height: 74px;
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 11px 12px;
    background: rgba(255, 255, 255, 0.025);
    color: var(--text-muted);
    text-align: left;
    cursor: pointer;
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    grid-template-rows: auto auto;
    column-gap: 10px;
    row-gap: 2px;
    align-items: center;
  }

  .override-option :global(svg) {
    grid-row: 1 / -1;
    color: var(--option-accent);
    opacity: 0.72;
  }

  .override-option:hover {
    border-color: color-mix(in srgb, var(--option-accent) 28%, var(--border-hover));
    background: color-mix(in srgb, var(--option-accent) 5%, rgba(255, 255, 255, 0.025));
  }

  .override-option.active {
    border-color: color-mix(in srgb, var(--option-accent) 42%, var(--border));
    background: color-mix(in srgb, var(--option-accent) 10%, rgba(255, 255, 255, 0.025));
    color: var(--text-primary);
  }

  .override-option-auto {
    --option-accent: var(--accent);
  }

  .override-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .override-note {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 10px;
    color: var(--text-muted);
  }

  @keyframes panelIn {
    from {
      opacity: 0;
      transform: translateY(-4px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .override-panel {
      animation: none;
    }

    .control-button-change :global(svg) {
      transition: none;
    }
  }

  @media (max-width: 760px) {
    .control-summary {
      align-items: flex-start;
      flex-direction: column;
      gap: 13px;
    }

    .control-actions {
      width: 100%;
      justify-content: flex-start;
    }

    .override-panel {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  @media (max-width: 480px) {
    .activity-control {
      border-radius: 14px;
    }

    .control-summary {
      padding: 15px;
    }

    .control-actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .control-button {
      width: 100%;
    }

    .control-button-danger:last-child:nth-child(3) {
      grid-column: 1 / -1;
    }

    .override-panel {
      gap: 7px;
      padding: 0 15px 15px;
    }

    .override-option {
      min-height: 68px;
      padding: 10px;
    }
  }
</style>
