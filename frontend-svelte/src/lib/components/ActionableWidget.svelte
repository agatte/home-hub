<script>
  /** @type {string} */
  export let ariaLabel
  /** @type {string} */
  export let className = ''
  /** @type {() => void | Promise<void>} */
  export let onActivate

  /** @param {MouseEvent} event */
  function handleClick(event) {
    const target = event.target
    const interactive = target instanceof Element
      ? target.closest('button, a, input, select, textarea, [role="button"]')
      : null
    if (interactive && interactive !== event.currentTarget) return
    onActivate?.()
  }

  /** @param {KeyboardEvent} event */
  function handleKeydown(event) {
    if (event.target !== event.currentTarget) return
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    onActivate?.()
  }
</script>

<div
  class={`widget widget-actionable ${className}`}
  role="button"
  tabindex="0"
  aria-label={ariaLabel}
  on:click={handleClick}
  on:keydown={handleKeydown}
>
  <slot />
</div>

<style>
  .widget-actionable {
    cursor: pointer;
  }

  .widget-actionable:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
</style>
