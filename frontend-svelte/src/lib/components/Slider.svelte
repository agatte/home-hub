<script>
  export let value = 0
  export let min = 0
  export let max = 100
  /** @type {string | undefined} */
  export let label = undefined
  export let className = ''
  /** When false, onChange only fires on release (mouseup/touchend). */
  export let liveUpdate = true
  /** @type {(v: number) => void} */
  export let onChange = () => {}
  /** Always fires on release with the final value, even when liveUpdate is true.
   *  Lets the parent flush any pending throttled updates so the bulb lands on
   *  the user's final position. */
  /** @type {(v: number) => void} */
  export let onCommit = () => {}

  let displayValue = value
  $: if (!dragging) displayValue = value

  let dragging = false

  /** @param {Event} e */
  function handleInput(e) {
    dragging = true
    const target = /** @type {HTMLInputElement} */ (e.target)
    displayValue = Number(target.value)
    if (liveUpdate) onChange(displayValue)
  }

  /** @param {Event} e */
  function handleCommit(e) {
    const target = /** @type {HTMLInputElement} */ (e.target)
    const val = Number(target.value)
    displayValue = val
    if (!liveUpdate) onChange(val)
    onCommit(val)
    dragging = false
  }
</script>

<label class="slider-container {className}">
  {#if label}
    <span class="slider-label">{label}</span>
  {/if}
  <input
    type="range"
    {min}
    {max}
    value={displayValue}
    on:input={handleInput}
    on:change={handleCommit}
    on:pointerup={handleCommit}
    on:pointercancel={handleCommit}
    class="slider-input"
  />
  <span class="slider-value">{displayValue}</span>
</label>
