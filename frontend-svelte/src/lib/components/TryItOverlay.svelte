<script>
  export let sceneName = ''
  export let remainingSeconds = 30
  /** @type {() => void} */
  export let onCancel = () => {}

  $: minutes = Math.floor(remainingSeconds / 60)
  $: seconds = remainingSeconds % 60
  $: timeDisplay = minutes > 0
    ? `${minutes}:${String(seconds).padStart(2, '0')}`
    : `${seconds}s`
</script>

<div class="try-it-bar">
  <div class="try-it-progress" style="width: {(remainingSeconds / 30) * 100}%"></div>
  <div class="try-it-content">
    <span class="try-it-label">
      <span class="try-it-scene">{sceneName}</span>
      <span class="try-it-time">{timeDisplay} remaining</span>
    </span>
    <button class="try-it-cancel" on:click={onCancel}>Cancel</button>
  </div>
</div>

<style>
  .try-it-bar {
    position: relative;
    overflow: hidden;
    border-radius: 8px;
    background: rgba(10, 10, 15, 0.6);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border: 1px solid rgba(120, 220, 160, 0.15);
    animation: slideIn 0.25s ease-out;
  }

  .try-it-progress {
    position: absolute;
    top: 0;
    left: 0;
    height: 100%;
    background: rgba(120, 220, 160, 0.06);
    transition: width 1s linear;
    pointer-events: none;
  }

  .try-it-content {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    gap: 12px;
  }

  .try-it-label {
    display: flex;
    align-items: center;
    gap: 8px;
    font-family: var(--font-body);
    font-size: 12px;
  }

  .try-it-scene {
    color: var(--text-primary);
    font-weight: 600;
  }

  .try-it-time {
    color: rgba(120, 220, 160, 0.7);
    font-variant-numeric: tabular-nums;
  }

  .try-it-cancel {
    padding: 3px 10px;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.05);
    color: var(--text-secondary);
    font-family: var(--font-body);
    font-size: 11px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
  }

  .try-it-cancel:hover {
    background: rgba(255, 255, 255, 0.1);
    border-color: rgba(255, 255, 255, 0.2);
  }

  @keyframes slideIn {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
  }
</style>
