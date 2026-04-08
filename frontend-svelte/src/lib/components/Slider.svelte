<script>
  export let value = 0
  export let min = 0
  export let max = 100
  /** @type {string | undefined} */
  export let label = undefined
  export let className = ''
  /** @type {(v: number) => void} */
  export let onChange = () => {}

  /** @param {Event} e */
  function handle(e) {
    const target = /** @type {HTMLInputElement} */ (e.target)
    onChange(Number(target.value))
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
    {value}
    on:input={handle}
    class="slider-input"
  />
  <span class="slider-value">{value}</span>
</label>
