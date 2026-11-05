// Capture before shared bubbling activity listeners. Keep the shield across
// release and synthesized click, even after mouse movement starts waking.
// The overlay is only mounted on opt-in read-only native Quiet Atlas pages.
export function installAmbientWakeGuard(target, wake) {
  const events = [
    'mousemove', 'pointermove', 'pointerdown', 'pointerup', 'pointercancel',
    'mousedown', 'mouseup', 'touchstart', 'touchend', 'touchcancel', 'touchmove',
    'keydown', 'keyup', 'click', 'dblclick', 'contextmenu', 'wheel', 'scroll',
  ]
  const presses = new Set()
  let timer = null
  let completed = false
  const options = { capture: true, passive: false }

  function schedule(reset = false) {
    if (completed || suspended) return
    if (reset) {
      clearTimeout(timer)
      timer = null
    }
    if (timer === null) {
      timer = setTimeout(() => {
        completed = true
        wake()
      }, 400)
    }
  }

  function consume(event) {
    event.preventDefault()
    event.stopImmediatePropagation()
    const type = event.type
    const key = type.startsWith('key') ? 'key:' + (event.code || event.key || 'unknown')
      : type.startsWith('pointer') ? 'pointer:' + (event.pointerId ?? 0)
      : type.startsWith('touch') ? 'touch' : 'mouse:' + (event.button ?? 0)
    if (['keydown', 'pointerdown', 'mousedown', 'touchstart'].includes(type)) {
      presses.add(key)
      clearTimeout(timer)
      timer = null
      return
    }
    if (['keyup', 'pointerup', 'mouseup', 'touchend', 'pointercancel', 'touchcancel'].includes(type)) {
      if (!type.startsWith('touch') || !event.touches?.length) presses.delete(key)
      if (!presses.size) schedule(true)
      return
    }
    if (['click', 'dblclick', 'contextmenu'].includes(type)) {
      // Click cannot release unrelated held keys or another pointer.
      if (!presses.size) schedule(true)
      return
    }
    // Movement/scroll with no active press wakes, but the shield remains for
    // 400ms to swallow an immediate click on the previously covered control.
    if (!presses.size && ['mousemove', 'pointermove', 'touchmove', 'wheel', 'scroll'].includes(type)) {
      schedule()
    }
  }

  // Lost release events must not strand the shield after Alt-Tab or hiding.
  // Wait for focus/visibility to return before starting the full click shield.
  const doc = target.document
  let suspended = false
  function suspend() {
    suspended = true
    presses.clear()
    clearTimeout(timer)
    timer = null
  }
  function resume() {
    if (doc?.visibilityState === 'hidden') return
    if (suspended) { suspended = false; schedule(true) }
  }
  function visibility() {
    if (doc.visibilityState === 'hidden') suspend()
    else resume()
  }
  target.addEventListener('blur', suspend)
  target.addEventListener('focus', resume)
  doc?.addEventListener('visibilitychange', visibility)
  events.forEach(type => target.addEventListener(type, consume, options))
  return () => {
    completed = true
    clearTimeout(timer)
    presses.clear()
    target.removeEventListener('blur', suspend)
    target.removeEventListener('focus', resume)
    doc?.removeEventListener('visibilitychange', visibility)
    events.forEach(type => target.removeEventListener(type, consume, options))
  }
}
