import { afterEach, describe, expect, it, vi } from 'vitest'
import { compile } from 'svelte/compiler'
import { render } from '@testing-library/svelte'
import { tick } from 'svelte'
import { get } from 'svelte/store'
import Ambient from '../../src/lib/components/QuietAtlasAmbient.svelte'
import source from '../../src/lib/components/QuietAtlasAmbient.svelte?raw'
import layout from '../../src/routes/+layout.svelte?raw'
import { ambientContext, receiveAmbientContext, resetAmbientContext, ambientContent, ambientRouteEligible, ambientClockText, ambientDateText, AMBIENT_VIEWPORT } from '../../src/lib/quietAtlas/ambient.js'
import { installAmbientWakeGuard } from '../../src/lib/quietAtlas/ambientWake.js'
import { userIdle, initActivityTracking } from '../../src/lib/stores/activity.js'
import { connected } from '../../src/lib/stores/connection.js'
import { automation, initialAutomationState } from '../../src/lib/stores/automation.js'

afterEach(() => {
  vi.useRealTimers()
  connected.set(false)
  resetAmbientContext()
  automation.set(initialAutomationState)
  userIdle.set(false)
})

describe('first opt-in Quiet Atlas ambient candidate (#15, not full acceptance)', () => {
  it('permits only current native read-only routes with the desktop viewport gate', () => {
    for (const route of ['control', 'music', 'insights', 'settings']) {
      expect(ambientRouteEligible(`/quiet-atlas/${route}`)).toBe(true)
    }
    for (const route of ['/', '/quiet-atlas/home', '/quiet-atlas', '/quiet-atlas/future-functional', '/guest',
      '/gameday', '/settings', '/music', '/quiet-atlas/music/artist-review',
      '/quiet-atlas/music/artist-review/nested']) {
      expect(ambientRouteEligible(route)).toBe(false)
    }
    expect(AMBIENT_VIEWPORT).toBe('(min-width: 900px) and (orientation: landscape)')
    expect(layout).toContain('ambientViewport && ambientRouteEligible($page.url.pathname) && $userIdle')
    expect(layout).toContain('inert={ambientVisible}')
  })

  it('abstains on disconnected or missing/unknown state and never retains Away/Sleeping activity', () => {
    const home = { house_state: 'home', activity: 'idle' }
    expect(ambientContent(false, home)).toEqual({ house: null, activity: null })
    expect(ambientContent(true, home)).toEqual({ house: 'Home', activity: 'General' })
    for (const house_state of ['away', 'sleeping', 'winding_down', null, 'unknown']) {
      expect(ambientContent(true, { house_state, activity: 'idle' }).activity).toBeNull()
    }
    for (const house_state of ['away', 'sleeping']) {
      expect(ambientContent(true, { house_state, activity: 'gaming' }).activity).toBeNull()
    }
    expect(ambientContent(true, {}).house).toBeNull()
    expect(ambientContent(true, { house_state: 'unknown' }).house).toBeNull()
  })
  it('compiles both touched components and introduces no media/network requests', () => {
    for (const component of [source, layout]) {
      expect(compile(component, { generate: 'ssr' }).warnings).toEqual([])
    }
    expect(source).not.toMatch(/fetch\(|WebSocket|<img|art_url|setMode|setScene/)
    expect(source).toContain('15000')
    expect(source).toContain('prefers-reduced-motion: reduce')
  })

  it('formats the local device time and date at minute precision', () => {
    const a = new Date(2026, 10, 4, 12, 30)
    const b = new Date(2026, 10, 4, 12, 31)
    expect(ambientClockText(a)).not.toBe(ambientClockText(b))
    expect(ambientDateText(a)).toBe(ambientDateText(b))
    expect(source).toContain('setInterval(() => { now = new Date() }, 15000)')
    expect(source).toContain('clearInterval(timer)')
    expect(source).toContain('installAmbientWakeGuard(window, wakeActivity)')
  })

  it('renders unavailable truth and reacts to connected reported context without stale music', async () => {
    const view = render(Ambient)
    await tick()
    expect(view.getByText('HomeHub status unavailable')).toBeInTheDocument()
    connected.set(true)
    automation.set({ ...initialAutomationState, house_state: 'sleeping' })
    receiveAmbientContext({ house_state: 'home', activity: 'idle' })
    await tick()
    expect(view.container.querySelector('.context')?.textContent).toContain('HomeHub reports Home')
    expect(view.container.querySelector('.music')).toBeNull()
    connected.set(false)
    await tick()
    expect(view.queryByText('HomeHub status unavailable')).toBeInTheDocument()
    view.unmount()
  })
  it.each([
    ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'],
    ['touchstart', 'touchend', 'click'],
    ['touchstart', 'touchend'],
    ['keydown', 'keydown', 'keyup'],
  ])('consumes the whole wake sequence before bubbling activity/commands: %j', (...types) => {
    vi.useFakeTimers()
    const stopActivity = initActivityTracking()
    vi.advanceTimersByTime(60000)
    expect(get(userIdle)).toBe(true)
    const wake = vi.fn()
    const stopGuard = installAmbientWakeGuard(window, wake)
    const command = vi.fn()
    const button = document.createElement('button')
    document.body.append(button)
    button.addEventListener('click', command)
    window.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }))
    expect(get(userIdle)).toBe(true)
    for (const type of types) {
      const event = new Event(type, { bubbles: true, cancelable: true })
      button.dispatchEvent(event)
      expect(event.defaultPrevented).toBe(true)
    }
    expect(command).not.toHaveBeenCalled()
    expect(wake).not.toHaveBeenCalled()
    vi.advanceTimersByTime(400)
    expect(wake).toHaveBeenCalledOnce()
    stopGuard()
    window.dispatchEvent(new MouseEvent('mousemove'))
    expect(get(userIdle)).toBe(false)
    button.remove()
    stopActivity()
  })

  it('wakes safely from movement, scroll and cancelled press without a click', () => {
    vi.useFakeTimers()
    for (const sequence of [['mousemove'], ['wheel'], ['touchstart', 'touchcancel'], ['pointerdown', 'pointercancel']]) {
      const wake = vi.fn()
      const stop = installAmbientWakeGuard(window, wake)
      for (const type of sequence) {
        window.dispatchEvent(new Event(type, { bubbles: true, cancelable: true }))
      }
      vi.advanceTimersByTime(400)
      expect(wake).toHaveBeenCalledOnce()
      stop()
    }
  })
  it('shields a second click and cancels pending wake on route teardown', () => {
    vi.useFakeTimers()
    const wake = vi.fn()
    const stop = installAmbientWakeGuard(window, wake)
    window.dispatchEvent(new Event('click'))
    vi.advanceTimersByTime(200)
    window.dispatchEvent(new Event('mousedown'))
    vi.advanceTimersByTime(300)
    expect(wake).not.toHaveBeenCalled()
    window.dispatchEvent(new Event('mouseup'))
    window.dispatchEvent(new Event('click'))
    stop()
    vi.advanceTimersByTime(1000)
    expect(wake).not.toHaveBeenCalled()
  })
})

// Local proof for #15 P2 review: no production or device authority.
describe('ambient P2 regressions', () => {
  it('requires an explicit live receipt across reconnect and omitted fields', () => {
    resetAmbientContext()
    receiveAmbientContext({ mode: 'gaming', activity: 'gaming' })
    expect(get(ambientContext)).toBeNull()
    receiveAmbientContext({ house_state: 'home', activity: 'idle' })
    expect(ambientContent(true, get(ambientContext))).toEqual({ house: 'Home', activity: 'General' })
    receiveAmbientContext({ activity: 'working' })
    expect(get(ambientContext)?.activity).toBe('working')
    receiveAmbientContext({ mode: 'gaming' })
    expect(get(ambientContext)?.activity).toBe('working')
    receiveAmbientContext({ house_state: 'home' })
    expect(get(ambientContext)?.activity).toBeNull()
    for (const house_state of ['away', 'sleeping']) {
      receiveAmbientContext({ house_state, activity: 'gaming' })
      expect(ambientContent(true, get(ambientContext)).activity).toBeNull()
    }
    receiveAmbientContext({ house_state: 'unknown' })
    expect(get(ambientContext)).toBeNull()
    resetAmbientContext() // close/open boundary
    receiveAmbientContext({ mode: 'idle' })
    expect(ambientContent(true, get(ambientContext))).toEqual({ house: null, activity: null })
  })

  it('recovers a lost keyup after blur and focus with a full trailing-click shield', () => {
    vi.useFakeTimers()
    const wake = vi.fn()
    const stop = installAmbientWakeGuard(window, wake)
    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'AltLeft' }))
    window.dispatchEvent(new Event('blur'))
    vi.advanceTimersByTime(1000)
    expect(wake).not.toHaveBeenCalled()
    window.dispatchEvent(new Event('focus'))
    vi.advanceTimersByTime(300)
    const click = new Event('click', { cancelable: true })
    window.dispatchEvent(click)
    expect(click.defaultPrevented).toBe(true)
    vi.advanceTimersByTime(399)
    expect(wake).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(wake).toHaveBeenCalledOnce()
    stop()
  })

  it('resets held inputs when document visibility returns', () => {
    vi.useFakeTimers()
    const wake = vi.fn()
    const stop = installAmbientWakeGuard(window, wake)
    window.dispatchEvent(new Event('touchstart'))
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    document.dispatchEvent(new Event('visibilitychange'))
    vi.advanceTimersByTime(1000)
    expect(wake).not.toHaveBeenCalled()
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
    document.dispatchEvent(new Event('visibilitychange'))
    vi.advanceTimersByTime(400)
    expect(wake).toHaveBeenCalledOnce()
    stop()
    vi.restoreAllMocks()
  })

  it('holds the shield until all overlapping inputs release or cancel', () => {
    vi.useFakeTimers()
    const wake = vi.fn()
    const stop = installAmbientWakeGuard(window, wake)
    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyA' }))
    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyB' }))
    window.dispatchEvent(new Event('pointerdown'))
    window.dispatchEvent(new KeyboardEvent('keyup', { code: 'KeyA' }))
    window.dispatchEvent(new Event('pointercancel'))
    window.dispatchEvent(new Event('click'))
    vi.advanceTimersByTime(1000)
    expect(wake).not.toHaveBeenCalled()
    window.dispatchEvent(new KeyboardEvent('keyup', { code: 'KeyB' }))
    vi.advanceTimersByTime(400)
    expect(wake).toHaveBeenCalledOnce()
    stop()
  })

  it('keeps focus ownership in the root before inert and checks restoration after tick', () => {
    expect(layout).toContain('ambientFocus = document.activeElement')
    expect(layout).toContain('tick().then(() =>')
    expect(layout).toContain("previous.isConnected && !previous.closest('[inert]')")
    expect(layout).toContain('if (!wasAmbientVisible')
    expect(source).not.toContain('previousFocus')
    expect(source).toContain('resumeButton.focus({ preventScroll: true })')
    expect(source).not.toContain('$automation')
  })
})
