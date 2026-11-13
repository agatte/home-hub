<script>
  import { automation } from '$lib/stores/automation.js'
  import { setManualMode } from '$lib/stores/init.js'
  import { apiPost } from '$lib/api.js'
  import { modeColor } from '$lib/theme.js'
  import { Power, Gamepad2, Monitor, Tv, ChefHat, Flame, PartyPopper, Moon, Bot } from 'lucide-svelte'

  const CARDS = [
    { id: 'gaming',    label: 'Gaming',    icon: Gamepad2,     isAction: false },
    { id: 'working',   label: 'Working',   icon: Monitor,      isAction: false },
    { id: 'watching',  label: 'Watching',  icon: Tv,           isAction: false },
    { id: 'cooking',   label: 'Cooking',   icon: ChefHat,      isAction: false },
    { id: 'relax',     label: 'Relax',     icon: Flame,        isAction: false },
    { id: 'social',    label: 'Party',     icon: PartyPopper,  isAction: false },
    { id: 'sleeping',  label: 'Sleep',     icon: Moon,         isAction: false },
    { id: 'auto',      label: 'Auto',      icon: Bot,          isAction: false },
    { id: 'alloff',    label: 'All Off',   icon: Power,        isAction: true, color: '#f87171' },
  ]

  $: currentMode = $automation.mode
  $: userOverride = $automation.override_user_owned

  // Build a reactive map of which card is active — recalculates when
  // currentMode or userOverride change, which fixes the Svelte 4
  // @const reactivity issue that caused "if_block.p is not a function".
  $: activeMap = Object.fromEntries(CARDS.map(c => [
    c.id,
    c.isAction ? false : c.id === 'auto' ? !userOverride : userOverride && currentMode === c.id,
  ]))

  function cardColor(card) {
    if (card.color) return card.color
    return modeColor(card.id)
  }

  /** @type {string | null} */
  let pressedId = null
  /** @type {string | null} */
  let allOffFeedback = null
  let allOffPending = false

  async function handleClick(card) {
    if (card.isAction && allOffPending) return
    pressedId = card.id
    setTimeout(() => { pressedId = null }, 400)
    if (card.isAction) {
      allOffPending = true
      allOffFeedback = 'Sending All Off request to HomeHub…'
      try {
        // The backend may complete a subset and cannot undo a sent Hue frame.
        // Never suggest retrying on a timeout, partial result or missing reply.
        const outcome = await apiPost('/api/lights/all', { on: false }, { timeout: 20000 })
        if (outcome?.status === 'ok') {
          allOffFeedback = 'HomeHub acknowledged All Off. Verify the reported light states.'
        } else if (outcome?.status === 'partial_failure') {
          const blocked = Array.isArray(outcome.blocked) ? outcome.blocked.length : 0
          const unavailable = Array.isArray(outcome.unavailable) ? outcome.unavailable.length : 0
          const uncertain = Array.isArray(outcome.uncertain) ? outcome.uncertain.length : 0
          allOffFeedback = `All Off only partly applied: ${blocked} protected, ${unavailable} unavailable, ${uncertain} uncertain. Check the actual lights before taking another action.`
        } else {
          allOffFeedback = 'All Off result not confirmed. Check the lights before trying again.'
        }
      } catch {
        allOffFeedback = 'All Off result uncertain. Check the actual lights before trying again.'
      } finally {
        allOffPending = false
      }
    } else {
      await setManualMode(card.id)
    }
  }
</script>

<div class="mode-card-deck">
  <div class="card-row">
    {#each CARDS as card, i}
      {@const color = cardColor(card)}
      <button
        class="mode-card"
        class:mode-card-active={activeMap[card.id]}
        class:mode-card-pressing={pressedId === card.id}
        class:mode-card-danger={card.isAction}
        style="
          --mode-color: {color};
          --delay: {i * 40}ms;
          {activeMap[card.id] ? `--active-glow: ${color}30; --active-border: ${color}44; --active-bg: ${color}1f;` : ''}
        "
        on:click={() => handleClick(card)}
        aria-label={card.isAction ? 'Turn all lights off' : `${card.label} mode`}
        aria-pressed={activeMap[card.id]}
        disabled={card.isAction && allOffPending}
      >
        <div class="card-inner">
          <div class="card-front">
            <span class="card-label">{card.label}</span>
            <div class="card-icon">
              <svelte:component this={card.icon} size={22} strokeWidth={1.5} />
            </div>
          </div>
          <div class="card-back">
            <div class="card-art card-art-{card.id}"></div>
            <span class="card-back-label">{card.label}</span>
          </div>
        </div>
        {#if activeMap[card.id]}
          <div class="active-dot" style="background: {color}"></div>
        {/if}
      </button>
    {/each}
  </div>
  {#if allOffFeedback}
    <p class="all-off-feedback" role="status" aria-live="polite">{allOffFeedback}</p>
  {/if}
</div>

<style>
  .mode-card-deck {
    margin-top: 8px;
    margin-bottom: 20px;
  }

  .card-row {
    display: flex;
    gap: 12px;
    justify-content: center;
  }
  .all-off-feedback {
    margin: 10px 0 0;
    font-size: 12px;
    line-height: 1.5;
    text-align: center;
    color: var(--text-muted);
  }

  /* --- Card button --- */
  .mode-card {
    flex: 1 1 0;
    max-width: 115px;
    aspect-ratio: 2 / 3;
    perspective: 800px;
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    position: relative;
    animation: widgetFadeIn 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) both;
    animation-delay: var(--delay, 0ms);
  }

  .mode-card:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 3px;
    border-radius: 12px;
  }

  /* --- 3D flip container --- */
  .card-inner {
    position: relative;
    width: 100%;
    height: 100%;
    transform-style: preserve-3d;
    transition: transform 0.6s cubic-bezier(0.25, 0.1, 0.25, 1);
    border-radius: 12px;
  }

  @media (hover: hover) {
    .mode-card:not(.mode-card-pressing):hover .card-inner {
      transform: rotateY(180deg);
      will-change: transform;
    }
  }

  /* Click feedback — brief scale pulse */
  .mode-card-pressing .card-front {
    transform: scale(0.93);
  }

  /* --- Faces (shared) --- */
  .card-front,
  .card-back {
    position: absolute;
    inset: 0;
    backface-visibility: hidden;
    -webkit-backface-visibility: hidden;
    border-radius: 12px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* --- Front face --- */
  .card-front {
    background: var(--bg-card);
    backdrop-filter: var(--glass-blur) var(--glass-saturate);
    -webkit-backdrop-filter: var(--glass-blur) var(--glass-saturate);
    border: 1px solid var(--border);
    align-items: center;
    justify-content: center;
    gap: 8px;
    transition: border-color 0.2s, background 0.2s, box-shadow 0.2s, transform 0.2s;
  }

  .mode-card-active .card-front {
    border-color: var(--active-border);
    background: var(--active-bg);
    box-shadow: 0 8px 24px var(--active-glow);
    transform: translateY(-4px);
  }

  .mode-card-danger .card-front {
    border-color: rgba(248, 113, 113, 0.15);
  }

  @media (hover: hover) {
    .mode-card:not(.mode-card-active):hover .card-front {
      border-color: var(--border-hover);
      background: var(--bg-card-hover);
    }
  }

  .card-label {
    font-family: var(--font-display);
    font-size: 20px;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--text-primary);
    line-height: 1;
  }

  .mode-card-active .card-label {
    color: var(--mode-color);
  }

  .mode-card-danger .card-label {
    color: #f87171;
  }

  .card-icon {
    color: var(--text-muted);
    display: flex;
  }

  .mode-card-active .card-icon {
    color: var(--mode-color);
    opacity: 0.7;
  }

  .mode-card-danger .card-icon {
    color: rgba(248, 113, 113, 0.5);
  }

  /* --- Back face --- */
  .card-back {
    transform: rotateY(180deg);
    background: color-mix(in srgb, var(--mode-color) 12%, rgba(10, 10, 15, 0.85));
    border: 1px solid color-mix(in srgb, var(--mode-color) 25%, transparent);
    align-items: center;
    justify-content: flex-end;
    padding-bottom: 12px;
  }

  .card-back-label {
    font-family: var(--font-body);
    font-size: 11px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--mode-color);
    opacity: 0.8;
    position: relative;
    z-index: 1;
  }

  /* --- Card art (CSS-only illustrations) --- */
  .card-art {
    position: absolute;
    inset: 0;
    border-radius: 12px;
    overflow: hidden;
    opacity: 0.7;
  }

  /* All Off — fading radial pulse */
  .card-art-alloff {
    background: radial-gradient(circle at 50% 40%, #f8717140 0%, #f8717110 40%, transparent 70%);
  }
  .card-art-alloff::before {
    content: '';
    position: absolute;
    top: 25%;
    left: 50%;
    width: 30px;
    height: 30px;
    transform: translateX(-50%);
    border: 2px solid #f8717160;
    border-radius: 50%;
    border-top-color: transparent;
  }

  /* Gaming — rotated diamond */
  .card-art-gaming {
    background: linear-gradient(135deg, transparent 40%, var(--mode-color) 50%, transparent 60%);
  }
  .card-art-gaming::before {
    content: '';
    position: absolute;
    top: 20%;
    left: 50%;
    width: 40px;
    height: 40px;
    transform: translateX(-50%) rotate(45deg);
    border: 2px solid var(--mode-color);
    opacity: 0.6;
  }
  .card-art-gaming::after {
    content: '';
    position: absolute;
    top: 30%;
    left: 50%;
    width: 24px;
    height: 24px;
    transform: translateX(-50%) rotate(45deg);
    background: var(--mode-color);
    opacity: 0.2;
  }

  /* Working — dot grid */
  .card-art-working {
    background: radial-gradient(circle, var(--mode-color) 1px, transparent 1px);
    background-size: 12px 12px;
    opacity: 0.3;
  }

  /* Watching — concentric arcs */
  .card-art-watching::before,
  .card-art-watching::after {
    content: '';
    position: absolute;
    left: 50%;
    top: 35%;
    border-radius: 50%;
    border: 2px solid var(--mode-color);
    transform: translateX(-50%);
    opacity: 0.4;
  }
  .card-art-watching::before {
    width: 50px;
    height: 50px;
  }
  .card-art-watching::after {
    width: 30px;
    height: 30px;
    top: 40%;
    opacity: 0.6;
  }

  /* Cooking — radial heat from a stovetop burner */
  .card-art-cooking {
    background: radial-gradient(
      circle at 50% 65%,
      var(--mode-color) 0%,
      transparent 35%
    );
    opacity: 0.35;
  }
  .card-art-cooking::before {
    content: '';
    position: absolute;
    top: 55%;
    left: 50%;
    width: 38px;
    height: 38px;
    transform: translate(-50%, -50%);
    border: 2px solid var(--mode-color);
    border-radius: 50%;
    opacity: 0.55;
  }

  /* Relax — wavy diagonal lines */
  .card-art-relax {
    background: repeating-linear-gradient(
      -45deg,
      transparent,
      transparent 8px,
      var(--mode-color) 8px,
      var(--mode-color) 9px
    );
    opacity: 0.2;
  }
  .card-art-relax::before {
    content: '';
    position: absolute;
    top: 30%;
    left: 50%;
    width: 24px;
    height: 32px;
    transform: translateX(-50%);
    border-radius: 50% 50% 0 0;
    border: 2px solid var(--mode-color);
    border-bottom: none;
    opacity: 0.5;
  }

  /* Party — conic starburst */
  .card-art-social {
    background: conic-gradient(
      from 0deg at 50% 40%,
      var(--mode-color) 0deg,
      transparent 30deg,
      var(--mode-color) 60deg,
      transparent 90deg,
      var(--mode-color) 120deg,
      transparent 150deg,
      var(--mode-color) 180deg,
      transparent 210deg,
      var(--mode-color) 240deg,
      transparent 270deg,
      var(--mode-color) 300deg,
      transparent 330deg,
      var(--mode-color) 360deg
    );
    opacity: 0.2;
  }

  /* Sleeping — crescent moon */
  .card-art-sleeping::before {
    content: '';
    position: absolute;
    top: 22%;
    left: 50%;
    width: 36px;
    height: 36px;
    transform: translateX(-50%);
    border-radius: 50%;
    background: var(--mode-color);
    opacity: 0.4;
    box-shadow: 10px -6px 0 0 rgba(10, 10, 15, 0.85);
  }
  .card-art-sleeping::after {
    content: '';
    position: absolute;
    top: 55%;
    left: 30%;
    width: 3px;
    height: 3px;
    border-radius: 50%;
    background: var(--mode-color);
    opacity: 0.5;
    box-shadow:
      15px -8px 0 1px var(--mode-color),
      30px -3px 0 0 var(--mode-color),
      8px 8px 0 1px var(--mode-color);
  }

  /* Auto — stepped conic gear */
  .card-art-auto {
    background: conic-gradient(
      from 0deg at 50% 40%,
      var(--mode-color) 0deg 20deg,
      transparent 20deg 40deg,
      var(--mode-color) 40deg 60deg,
      transparent 60deg 80deg,
      var(--mode-color) 80deg 100deg,
      transparent 100deg 120deg,
      var(--mode-color) 120deg 140deg,
      transparent 140deg 160deg,
      var(--mode-color) 160deg 180deg,
      transparent 180deg 200deg,
      var(--mode-color) 200deg 220deg,
      transparent 220deg 240deg,
      var(--mode-color) 240deg 260deg,
      transparent 260deg 280deg,
      var(--mode-color) 280deg 300deg,
      transparent 300deg 320deg,
      var(--mode-color) 320deg 340deg,
      transparent 340deg 360deg
    );
    opacity: 0.2;
  }
  .card-art-auto::before {
    content: '';
    position: absolute;
    top: 30%;
    left: 50%;
    width: 20px;
    height: 20px;
    transform: translateX(-50%);
    border-radius: 50%;
    border: 2px solid var(--mode-color);
    opacity: 0.5;
  }

  /* --- Active dot indicator --- */
  .active-dot {
    position: absolute;
    top: -2px;
    left: 50%;
    transform: translateX(-50%);
    width: 6px;
    height: 6px;
    border-radius: 50%;
    z-index: 2;
    animation: dotFadeIn 0.3s ease-out;
  }

  @keyframes dotFadeIn {
    from { opacity: 0; transform: translateX(-50%) scale(0); }
    to { opacity: 1; transform: translateX(-50%) scale(1); }
  }

  /* --- Reduced motion --- */
  @media (prefers-reduced-motion: reduce) {
    .mode-card {
      animation: none;
    }
    .card-inner {
      transition: none;
    }
    .mode-card:hover .card-inner {
      transform: none;
    }
    /* Crossfade instead of flip */
    .card-front,
    .card-back {
      backface-visibility: visible;
      -webkit-backface-visibility: visible;
    }
    .card-back {
      transform: none;
      opacity: 0;
      transition: opacity 0.2s;
    }
    .card-front {
      transition: opacity 0.2s;
    }
    .mode-card:hover .card-back {
      opacity: 1;
    }
    .mode-card:hover .card-front {
      opacity: 0;
    }
  }

  /* --- Responsive --- */
  @media (max-width: 900px) and (min-width: 601px) {
    .card-row {
      flex-wrap: wrap;
    }
    .mode-card {
      max-width: 100px;
    }
  }

  /* The functional legacy handoff must not hide manual modes off-screen on phones.
     Keep DOM, touch, and keyboard order aligned: All Off is last and visually separate. */
  @media (max-width: 600px) {
    .card-row {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      justify-content: stretch;
    }
    .mode-card {
      width: 100%;
      min-width: 0;
      max-width: none;
      min-height: 64px;
      aspect-ratio: auto;
      flex: none;
    }
    .card-inner {
      min-height: 64px;
    }
    .card-front {
      padding: 4px;
      gap: 4px;
      box-sizing: border-box;
    }
    .card-icon {
      display: none;
    }
    .card-label {
      font-size: clamp(15px, 3.8vw, 17px);
      letter-spacing: 0.3px;
    }
    .mode-card-danger {
      grid-column: 1 / -1;
      min-height: 56px;
    }
    .mode-card-danger .card-inner {
      min-height: 56px;
    }
    .mode-card-danger .card-front {
      flex-direction: row;
      gap: 10px;
      background: rgba(248, 113, 113, 0.08);
    }
    .mode-card-danger .card-icon {
      display: flex;
    }
  }
</style>
