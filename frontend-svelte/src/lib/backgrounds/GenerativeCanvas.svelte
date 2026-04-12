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

  const noise3D = createNoise3D()
  const GRID_SIZE = 32
  let cols = 0
  let rows = 0
  let cellSize = 0

  // Current and target state (lerped during transitions)
  let currentParams = modeGenerative('idle')
  let targetParams = modeGenerative('idle')
  let paramLerpT = 1.0
  let time = 0

  // Color state
  let modeHex = '#6b7280'
  let secondaryHex = '#4b5563'
  let accentHex = '#374151'
  /** @type {Array<{h: number, s: number, l: number}>} */
  let colorPalette = [{ h: 0, s: 0, l: 0.45 }]

  // Music state
  let musicPlaying = false
  let musicPulse = 0 // 0..1 sine wave for blob pulse

  // Particles
  /** @type {Array<{x:number,y:number,vx:number,vy:number,color:number,life:number,maxLife:number}>} */
  let particles = []

  // Blob positions (persistent, drift via noise)
  /** @type {Array<{nx:number,ny:number,phase:number}>} */
  let blobs = []

  // --- Store subscriptions ---
  const unsubMode = automation.subscribe(($auto) => {
    targetParams = modeGenerative($auto.mode)
    modeHex = modeColor($auto.mode)
    secondaryHex = targetParams.secondaryColor || modeHex
    accentHex = targetParams.accentColor || secondaryHex
    paramLerpT = 0.0
    // Re-seed blobs if count changed
    while (blobs.length < (targetParams.blobCount || 2)) {
      blobs.push({ nx: Math.random() * 10, ny: Math.random() * 10, phase: Math.random() * Math.PI * 2 })
    }
  })

  const unsubLights = lights.subscribe(($lights) => {
    const onLights = Object.values($lights).filter((l) => l.on && l.reachable)
    if (onLights.length === 0) {
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
    musicPlaying = $sonos.state === 'PLAYING'
  })

  function hueToHSL(hue, sat, bri) {
    return {
      h: (hue / 65535) * 360,
      s: (sat / 254) * 100,
      l: Math.max(20, Math.min(70, (bri / 254) * 60 + 15)),
    }
  }

  function lerp(a, b, t) { return a + (b - a) * t }

  function lerpParams(a, b, t) {
    const r = {}
    for (const key of Object.keys(b)) {
      if (typeof b[key] === 'number' && typeof a[key] === 'number') {
        r[key] = key === 'particleCount' || key === 'blobCount'
          ? Math.round(lerp(a[key], b[key], t))
          : lerp(a[key], b[key], t)
      } else {
        r[key] = t > 0.5 ? b[key] : a[key] // snap strings at midpoint
      }
    }
    return r
  }

  /** Parse hex color to {r,g,b} 0-255 */
  function hexToRGB(hex) {
    const n = parseInt(hex.slice(1), 16)
    return { r: (n >> 16) & 0xff, g: (n >> 8) & 0xff, b: n & 0xff }
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
    particles = []
    for (let i = 0; i < (currentParams.particleCount || 60); i++) {
      particles.push(createParticle())
    }
  }

  function createParticle() {
    const w = canvas?.clientWidth || 1920
    const h = canvas?.clientHeight || 1080
    const style = currentParams.particleStyle || 'dots'
    return {
      x: Math.random() * w,
      y: style === 'embers' ? h + Math.random() * 20 : Math.random() * h,
      vx: 0,
      vy: style === 'embers' ? -(Math.random() * 0.5 + 0.3) : 0,
      color: Math.floor(Math.random() * colorPalette.length),
      life: Math.random() * 200 + 100,
      maxLife: 300,
    }
  }

  // ── Layer 1: Gradient Mesh Blobs ──────────────────────────────────
  function drawBlobs(w, h) {
    const count = currentParams.blobCount || 2
    const baseOpacity = currentParams.blobOpacity || 0.08
    const speed = currentParams.blobSpeed || 0.1
    const pulse = currentParams.musicBlobPulse || 0

    const colors = [modeHex, secondaryHex, accentHex]

    for (let i = 0; i < count; i++) {
      if (i >= blobs.length) break
      const b = blobs[i]

      // Drift position via noise
      const bx = (noise3D(b.nx, 0, time * speed * 0.3) * 0.5 + 0.5) * w
      const by = (noise3D(0, b.ny, time * speed * 0.3 + 100) * 0.5 + 0.5) * h

      // Music pulse: scale radius with sine wave
      const pulseScale = musicPlaying ? 1 + Math.sin(musicPulse + b.phase) * pulse : 1
      const radius = Math.min(w, h) * (0.3 + i * 0.05) * pulseScale

      const c = hexToRGB(colors[i % colors.length])
      const grad = ctx.createRadialGradient(bx, by, 0, bx, by, radius)
      grad.addColorStop(0, `rgba(${c.r}, ${c.g}, ${c.b}, ${baseOpacity})`)
      grad.addColorStop(0.5, `rgba(${c.r}, ${c.g}, ${c.b}, ${baseOpacity * 0.4})`)
      grad.addColorStop(1, `rgba(${c.r}, ${c.g}, ${c.b}, 0)`)

      ctx.fillStyle = grad
      ctx.fillRect(0, 0, w, h)
    }
  }

  // ── Layer 2: Particle Field ───────────────────────────────────────
  function updateAndDrawParticles(w, h) {
    const style = currentParams.particleStyle || 'dots'
    const size = currentParams.particleSize || 2
    const intensity = currentParams.particleIntensity || 0.2
    const speedMult = musicPlaying ? (currentParams.musicSpeedBoost || 1.0) : 1.0

    // Adjust particle count
    const target = currentParams.particleCount || 60
    while (particles.length < target) particles.push(createParticle())
    if (particles.length > target + 20) particles.length = target

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i]

      if (style === 'embers') {
        // Embers float upward with gentle horizontal drift
        const drift = noise3D(p.x * 0.005, p.y * 0.005, time) * 0.8
        p.vx = p.vx * 0.9 + drift * 0.3
        p.vy = p.vy * 0.95 - 0.15 * speedMult
        p.x += p.vx
        p.y += p.vy
        p.life -= 1
      } else {
        // Flow field (dots and streaks)
        const gridX = Math.floor(p.x / cellSize)
        const gridY = Math.floor(p.y / cellSize)
        const freq = currentParams.noiseFrequency || 0.3
        const noiseVal = noise3D(gridX * freq * 0.1, gridY * freq * 0.1, time)
        const angle = noiseVal * Math.PI * 2

        const accel = style === 'streaks' ? 1.2 : 0.6
        p.vx = p.vx * 0.85 + Math.cos(angle) * accel * speedMult
        p.vy = p.vy * 0.85 + Math.sin(angle) * accel * speedMult
        p.x += p.vx
        p.y += p.vy
        p.life -= 1
      }

      // Respawn
      if (p.x < -10 || p.x > w + 10 || p.y < -10 || p.y > h + 10 || p.life <= 0) {
        particles[i] = createParticle()
        continue
      }

      // Draw
      const c = colorPalette[p.color % colorPalette.length]
      const fadeIn = p.life > (p.maxLife - 30) ? (p.maxLife - p.life) / 30 : 1
      const fadeOut = p.life < 30 ? p.life / 30 : 1
      const alpha = intensity * fadeIn * fadeOut

      if (style === 'streaks') {
        // Draw a short line in the direction of travel
        const len = Math.sqrt(p.vx * p.vx + p.vy * p.vy) * 3
        ctx.strokeStyle = `hsla(${c.h}, ${c.s}%, ${c.l}%, ${alpha})`
        ctx.lineWidth = size * 0.6
        ctx.lineCap = 'round'
        ctx.beginPath()
        ctx.moveTo(p.x, p.y)
        ctx.lineTo(p.x - (p.vx / (Math.abs(p.vx) + 0.1)) * len, p.y - (p.vy / (Math.abs(p.vy) + 0.1)) * len)
        ctx.stroke()
      } else if (style === 'embers') {
        // Warm glow dot with soft edge
        const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, size * 1.5)
        grad.addColorStop(0, `hsla(${c.h}, ${c.s}%, ${Math.min(80, c.l + 20)}%, ${alpha})`)
        grad.addColorStop(1, `hsla(${c.h}, ${c.s}%, ${c.l}%, 0)`)
        ctx.fillStyle = grad
        ctx.fillRect(p.x - size * 1.5, p.y - size * 1.5, size * 3, size * 3)
      } else {
        // Standard dot
        ctx.fillStyle = `hsla(${c.h}, ${c.s}%, ${c.l}%, ${alpha})`
        ctx.beginPath()
        ctx.arc(p.x, p.y, size, 0, Math.PI * 2)
        ctx.fill()
      }
    }
  }

  // ── Layer 3: Geometric Overlay ────────────────────────────────────
  function drawGeoOverlay(w, h) {
    const pattern = currentParams.geoPattern || 'none'
    if (pattern === 'none') return

    let opacity = currentParams.geoOpacity || 0.04
    // Music pulse on geo layer
    if (musicPlaying && currentParams.musicBlobPulse > 0.05) {
      opacity *= 1 + Math.sin(musicPulse * 1.5) * 0.3
    }

    const mc = hexToRGB(modeHex)
    ctx.strokeStyle = `rgba(${mc.r}, ${mc.g}, ${mc.b}, ${opacity})`
    ctx.lineWidth = 1

    if (pattern === 'grid') {
      // Dot grid — subtle graph paper feel
      const spacing = 40
      ctx.fillStyle = `rgba(${mc.r}, ${mc.g}, ${mc.b}, ${opacity * 0.8})`
      for (let x = spacing; x < w; x += spacing) {
        for (let y = spacing; y < h; y += spacing) {
          ctx.beginPath()
          ctx.arc(x, y, 1.2, 0, Math.PI * 2)
          ctx.fill()
        }
      }
    } else if (pattern === 'hex') {
      // Hexagonal grid with pulse
      const size = 50
      const sqrt3 = Math.sqrt(3)
      const pulsePhase = time * 2
      for (let row = -1; row < h / (size * 1.5) + 1; row++) {
        for (let col = -1; col < w / (size * sqrt3) + 1; col++) {
          const cx = col * size * sqrt3 + (row % 2 ? size * sqrt3 * 0.5 : 0)
          const cy = row * size * 1.5
          // Distance-based pulse
          const dist = Math.sqrt((cx - w / 2) ** 2 + (cy - h / 2) ** 2)
          const pulse = Math.sin(dist * 0.01 - pulsePhase) * 0.5 + 0.5
          const hexOp = opacity * (0.3 + pulse * 0.7)
          ctx.strokeStyle = `rgba(${mc.r}, ${mc.g}, ${mc.b}, ${hexOp})`
          ctx.beginPath()
          for (let s = 0; s < 6; s++) {
            const a = Math.PI / 3 * s - Math.PI / 6
            const px = cx + Math.cos(a) * size * 0.4
            const py = cy + Math.sin(a) * size * 0.4
            s === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py)
          }
          ctx.closePath()
          ctx.stroke()
        }
      }
    } else if (pattern === 'waves') {
      // Horizontal wave lines
      const waveCount = 6
      const spacing = h / (waveCount + 1)
      for (let i = 1; i <= waveCount; i++) {
        const baseY = i * spacing
        ctx.beginPath()
        for (let x = 0; x <= w; x += 4) {
          const wave = Math.sin(x * 0.008 + time * 0.5 + i * 0.8) * 15
          const noise = noise3D(x * 0.002, i * 0.5, time * 0.2) * 8
          const y = baseY + wave + noise
          x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
        }
        ctx.stroke()
      }
    } else if (pattern === 'rings') {
      // Concentric rings from center, slowly pulsing
      const cx = w / 2
      const cy = h / 2
      const maxR = Math.max(w, h) * 0.5
      const ringSpacing = 60
      for (let r = ringSpacing; r < maxR; r += ringSpacing) {
        const pulse = Math.sin(r * 0.02 - time * 0.3) * 0.5 + 0.5
        const ringOp = opacity * (0.4 + pulse * 0.6)
        ctx.strokeStyle = `rgba(${mc.r}, ${mc.g}, ${mc.b}, ${ringOp})`
        ctx.beginPath()
        ctx.arc(cx, cy, r, 0, Math.PI * 2)
        ctx.stroke()
      }
    } else if (pattern === 'radial') {
      // Radiating circles pulsing outward from center
      const cx = w / 2
      const cy = h / 2
      const maxR = Math.max(w, h) * 0.6
      const ringCount = 8
      for (let i = 0; i < ringCount; i++) {
        const phase = (time * 0.4 + i / ringCount) % 1
        const r = phase * maxR
        const fadeAlpha = opacity * (1 - phase) * 1.5
        ctx.strokeStyle = `rgba(${mc.r}, ${mc.g}, ${mc.b}, ${Math.min(fadeAlpha, opacity * 1.5)})`
        ctx.beginPath()
        ctx.arc(cx, cy, r, 0, Math.PI * 2)
        ctx.stroke()
      }
    }
  }

  // ── Main animation loop ───────────────────────────────────────────
  function animate(timestamp) {
    animationId = requestAnimationFrame(animate)

    const elapsed = timestamp - lastFrameTime
    if (elapsed < FRAME_INTERVAL) return
    lastFrameTime = timestamp - (elapsed % FRAME_INTERVAL)

    if (!ctx || !canvas) return

    const w = canvas.clientWidth
    const h = canvas.clientHeight

    // Interpolate params
    if (paramLerpT < 1.0) {
      paramLerpT = Math.min(1.0, paramLerpT + 0.02)
      currentParams = lerpParams(currentParams, targetParams, paramLerpT)
    }

    // Music pulse oscillator (~2s period at 15fps)
    if (musicPlaying) {
      musicPulse += 0.21 // ~2s full cycle at 15fps
    } else {
      musicPulse *= 0.95 // decay
    }

    // Update time
    const speed = currentParams.particleSpeed || 0.1
    const speedMult = musicPlaying ? (currentParams.musicSpeedBoost || 1.0) : 1.0
    time += speed * speedMult * 0.01

    // 1. Fade previous frame
    const trail = currentParams.particleTrail || 0.04
    ctx.fillStyle = `rgba(8, 8, 12, ${trail})`
    ctx.fillRect(0, 0, w, h)

    // 2. Gradient mesh blobs
    drawBlobs(w, h)

    // 3. Particles
    updateAndDrawParticles(w, h)

    // 4. Geometric overlay
    drawGeoOverlay(w, h)
  }

  function handleResize() { initCanvas() }

  onMount(() => {
    initCanvas()
    animationId = requestAnimationFrame(animate)
    window.addEventListener('resize', handleResize)

    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    if (motionQuery.matches) {
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
