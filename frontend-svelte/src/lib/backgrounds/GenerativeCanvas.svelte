<script>
  import { onMount, onDestroy } from 'svelte'
  import { createNoise3D } from 'simplex-noise'
  import { lights } from '$lib/stores/lights.js'
  import { sonos } from '$lib/stores/sonos.js'
  import { automation } from '$lib/stores/automation.js'
  import { modeGenerative, modeColor } from '$lib/theme.js'

  /** @type {HTMLCanvasElement} */
  let canvas
  /** @type {CanvasRenderingContext2D} */
  let ctx
  let animationId = 0
  let lastFrameTime = 0
  const TARGET_FPS = 15
  const FRAME_INTERVAL = 1000 / TARGET_FPS

  // Noise generator
  const noise3D = createNoise3D()

  // Flow field grid
  const GRID_SIZE = 32
  let cols = 0
  let rows = 0
  let cellSize = 0

  // Current state (reactively updated from stores)
  let currentParams = modeGenerative('idle')
  let targetParams = modeGenerative('idle')
  let paramLerpT = 1.0 // 0..1, 1 = fully at target
  let colorPalette = [{ h: 0, s: 0, l: 0.5 }] // monochrome default
  let speedMultiplier = 1.0
  let targetSpeedMultiplier = 1.0

  /** @type {Array<{x: number, y: number, vx: number, vy: number, color: number, life: number}>} */
  let particles = []
  let time = 0

  // Subscribe to stores
  const unsubMode = automation.subscribe(($auto) => {
    targetParams = modeGenerative($auto.mode)
    paramLerpT = 0.0 // start interpolating
  })

  const unsubLights = lights.subscribe(($lights) => {
    const onLights = Object.values($lights).filter((l) => l.on && l.reachable)
    if (onLights.length === 0) {
      // Monochrome drift when all lights off
      colorPalette = [
        { h: 0, s: 0, l: 0.45 },
        { h: 0, s: 0, l: 0.55 },
        { h: 0, s: 0, l: 0.35 },
      ]
    } else {
      colorPalette = onLights.map((l) => hueToHSL(l.hue, l.sat, l.bri))
    }
  })

  const unsubSonos = sonos.subscribe(($sonos) => {
    targetSpeedMultiplier = $sonos.state === 'PLAYING' ? 1.3 : 1.0
  })

  /**
   * Convert Hue bridge hue/sat/bri to HSL for canvas rendering.
   * Hue range: 0-65535, Sat: 0-254, Bri: 0-254
   */
  function hueToHSL(hue, sat, bri) {
    return {
      h: (hue / 65535) * 360,
      s: (sat / 254) * 100,
      l: Math.max(20, Math.min(70, (bri / 254) * 60 + 15)),
    }
  }

  /** Lerp between two values */
  function lerp(a, b, t) {
    return a + (b - a) * t
  }

  /** Lerp generative params */
  function lerpParams(a, b, t) {
    return {
      frequency: lerp(a.frequency, b.frequency, t),
      speed: lerp(a.speed, b.speed, t),
      particleCount: Math.round(lerp(a.particleCount, b.particleCount, t)),
      trailAlpha: lerp(a.trailAlpha, b.trailAlpha, t),
      intensity: lerp(a.intensity, b.intensity, t),
    }
  }

  function initCanvas() {
    if (!canvas) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = canvas.clientWidth * dpr
    canvas.height = canvas.clientHeight * dpr
    ctx = canvas.getContext('2d')
    ctx.scale(dpr, dpr)

    cols = GRID_SIZE
    rows = Math.round((canvas.clientHeight / canvas.clientWidth) * GRID_SIZE)
    cellSize = canvas.clientWidth / cols

    // Re-init particles
    const count = currentParams.particleCount
    particles = []
    for (let i = 0; i < count; i++) {
      particles.push(createParticle())
    }
  }

  function createParticle() {
    const w = canvas?.clientWidth || 1920
    const h = canvas?.clientHeight || 1080
    return {
      x: Math.random() * w,
      y: Math.random() * h,
      vx: 0,
      vy: 0,
      color: Math.floor(Math.random() * colorPalette.length),
      life: Math.random() * 200 + 100,
    }
  }

  function animate(timestamp) {
    animationId = requestAnimationFrame(animate)

    // Frame rate limiting
    const elapsed = timestamp - lastFrameTime
    if (elapsed < FRAME_INTERVAL) return
    lastFrameTime = timestamp - (elapsed % FRAME_INTERVAL)

    if (!ctx || !canvas) return

    const w = canvas.clientWidth
    const h = canvas.clientHeight

    // Interpolate params during mode transitions
    if (paramLerpT < 1.0) {
      paramLerpT = Math.min(1.0, paramLerpT + 0.02) // ~800ms at 15fps
      currentParams = lerpParams(currentParams, targetParams, paramLerpT)
    }

    // Smooth speed multiplier
    speedMultiplier = lerp(speedMultiplier, targetSpeedMultiplier, 0.05)

    // Adjust particle count
    while (particles.length < currentParams.particleCount) {
      particles.push(createParticle())
    }
    if (particles.length > currentParams.particleCount + 20) {
      particles.length = currentParams.particleCount
    }

    // Fade trails
    ctx.fillStyle = `rgba(8, 8, 12, ${currentParams.trailAlpha})`
    ctx.fillRect(0, 0, w, h)

    // Update time
    time += currentParams.speed * speedMultiplier * 0.01

    // Update and draw particles
    for (let i = 0; i < particles.length; i++) {
      const p = particles[i]

      // Sample flow field
      const gridX = Math.floor(p.x / cellSize)
      const gridY = Math.floor(p.y / cellSize)
      const noiseVal = noise3D(
        gridX * currentParams.frequency * 0.1,
        gridY * currentParams.frequency * 0.1,
        time
      )
      const angle = noiseVal * Math.PI * 2

      // Update velocity with some inertia
      p.vx = p.vx * 0.85 + Math.cos(angle) * 0.6
      p.vy = p.vy * 0.85 + Math.sin(angle) * 0.6

      // Move
      p.x += p.vx
      p.y += p.vy
      p.life -= 1

      // Wrap around edges or respawn
      if (p.x < 0 || p.x > w || p.y < 0 || p.y > h || p.life <= 0) {
        const np = createParticle()
        particles[i] = np
        continue
      }

      // Draw
      const c = colorPalette[p.color % colorPalette.length]
      const alpha = currentParams.intensity * (p.life > 30 ? 1 : p.life / 30)
      ctx.fillStyle = `hsla(${c.h}, ${c.s}%, ${c.l}%, ${alpha})`
      ctx.beginPath()
      ctx.arc(p.x, p.y, 1.5, 0, Math.PI * 2)
      ctx.fill()
    }
  }

  function handleResize() {
    initCanvas()
  }

  onMount(() => {
    initCanvas()
    animationId = requestAnimationFrame(animate)
    window.addEventListener('resize', handleResize)

    // Check reduced motion preference
    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    if (motionQuery.matches) {
      // Render a single frame then stop
      cancelAnimationFrame(animationId)
    }
  })

  onDestroy(() => {
    cancelAnimationFrame(animationId)
    window.removeEventListener('resize', handleResize)
    unsubMode()
    unsubLights()
    unsubSonos()
  })
</script>

<canvas bind:this={canvas} class="generative-canvas"></canvas>

<style>
  .generative-canvas {
    position: fixed;
    inset: 0;
    width: 100%;
    height: 100%;
    z-index: 0;
    pointer-events: none;
  }
</style>
