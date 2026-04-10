<script>
  import { automation } from '$lib/stores/automation.js'
  import { setManualMode } from '$lib/stores/init.js'
  import { apiPost } from '$lib/api.js'
  import { Clapperboard, Flame, PartyPopper, Moon, RotateCcw, Power } from 'lucide-svelte'

  const ACTIONS = [
    { id: 'movie', label: 'Movie', mode: 'movie', icon: Clapperboard },
    { id: 'relax', label: 'Relax', mode: 'relax', icon: Flame },
    { id: 'social', label: 'Party', mode: 'social', icon: PartyPopper },
    { id: 'sleeping', label: 'Bedtime', mode: 'sleeping', icon: Moon },
    { id: 'auto', label: 'Auto', mode: 'auto', icon: RotateCcw },
  ]

  $: currentMode = $automation.mode

  async function allOff() {
    try {
      await apiPost('/api/lights/all', { on: false })
    } catch {
      /* ignore */
    }
  }
</script>

<div class="quick-actions">
  <button class="quick-pill quick-pill-danger" on:click={allOff} aria-label="All lights off" title="All off">
    <Power size={16} strokeWidth={1.5} />
  </button>
  {#each ACTIONS as action}
    <button
      class="quick-pill"
      class:quick-pill-active={currentMode === action.mode}
      on:click={() => setManualMode(action.mode)}
      aria-label={action.label}
      title={action.label}
    >
      <svelte:component this={action.icon} size={16} strokeWidth={1.5} />
    </button>
  {/each}
</div>

<style>
  .quick-actions {
    display: flex;
    gap: 8px;
    margin-bottom: 20px;
    flex-wrap: wrap;
  }

  .quick-pill {
    width: 40px;
    height: 40px;
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

  .quick-pill:hover {
    border-color: var(--border-hover);
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.04);
  }

  .quick-pill-active {
    background: rgba(74, 108, 247, 0.12);
    border-color: rgba(74, 108, 247, 0.3);
    color: var(--accent);
  }

  .quick-pill-danger {
    color: var(--danger);
    border-color: rgba(248, 113, 113, 0.2);
  }

  .quick-pill-danger:hover {
    background: rgba(248, 113, 113, 0.1);
    border-color: rgba(248, 113, 113, 0.4);
    color: var(--danger);
  }
</style>
