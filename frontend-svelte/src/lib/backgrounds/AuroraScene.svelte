<script>
  import { onMount, onDestroy } from 'svelte'
  import { createNoise3D } from 'simplex-noise'
  import { sonos } from '$lib/stores/sonos.js'
  import { createAnimationLoop, createStars, initSceneCanvas } from './scene-utils.js'

  /** @type {HTMLCanvasElement} */
  let canvas
  /** @type {CanvasRenderingContext2D} */
  let ctx
  let w = 1920
  let h = 1080
  let stopLoop = () => {}
  let musicPlaying = false
  const noise3D = createNoise3D()

  const unsub = sonos.subscribe(($s) => { musicPlaying = $s.state === 'PLAYING' })

  /** @type {Array<{x:number,y:number,phase:number,size:number}>} */
  let stars = []
  /** @type {number[]} */
  let treeline = []

  // Aurora is drawn as vertical columns, each with noise-driven brightness
  // and smooth vertical gradients — no horizontal banding.

  function generateTreeline() {
    treeline = []
    const baseY = h * 0.85
    for (let x = 0; x <= w; x += 1) {
      const hill = Math.sin(x * 0.002) * 25 + Math.sin(x * 0.007) * 12
      // Spruce-tree spikes using triangle waves
      const treeFreq = 0.04 + Math.sin(x * 0.003) * 0.01
      const treePeak = Math.max(0, Math.sin(x * treeFreq)) ** 3 * 25
      treeline.push(baseY - hill - treePeak)
    }
  }

  function drawFrame(time) {
    if (!ctx) return

    const speedMult = musicPlaying ? 1.4 : 1.0
    const brightMult = musicPlaying ? 1.3 : 1.0

    // --- Sky ---
    const skyGrad = ctx.createLinearGradient(0, 0, 0, h)
    skyGrad.addColorStop(0, '#020206')
    skyGrad.addColorStop(0.3, '#040410')
    skyGrad.addColorStop(0.6, '#06081a')
    skyGrad.addColorStop(1, '#080a14')
    ctx.fillStyle = skyGrad
    ctx.fillRect(0, 0, w, h)

    // --- Stars ---
    for (const s of stars) {
      const twinkle = Math.sin(time * 1.5 + s.phase) * 0.5 + 0.5
      ctx.globalAlpha = 0.15 + twinkle * 0.5
      ctx.fillStyle = '#ffffff'
      ctx.beginPath()
      ctx.arc(s.x, s.y, s.size * 0.7, 0, Math.PI * 2)
      ctx.fill()
    }
    ctx.globalAlpha = 1

    // --- Aurora (column-based with noise for organic shape) ---
    // Draw vertical columns across the screen. Each column's brightness
    // and vertical extent is driven by 2D noise, creating smooth organic
    // curtain shapes instead of banded horizontal strips.
    const columnStep = 3
    const auroraTop = h * 0.05
    const auroraBot = h * 0.65

    for (let x = 0; x < w; x += columnStep) {
      const nx = x / w

      // Sample noise at different scales for layered curtain effect
      const n1 = noise3D(nx * 3, time * 0.04 * speedMult, 0) * 0.5 + 0.5
      const n2 = noise3D(nx * 6, time * 0.07 * speedMult, 10) * 0.5 + 0.5
      const n3 = noise3D(nx * 1.5, time * 0.02 * speedMult, 20) * 0.5 + 0.5

      // Combine noise layers — n1 for broad shape, n2 for detail, n3 for slow drift
      const intensity = (n1 * 0.5 + n2 * 0.3 + n3 * 0.2)

      if (intensity < 0.15) continue // skip dark areas for performance

      // Color: shift from green → cyan → purple across x and with noise
      const hue = 140 + n2 * 60 - n3 * 40 // 100-200 range (green-cyan with purple variance)
      const sat = 55 + intensity * 20
      const light = 30 + intensity * 25

      // Vertical gradient for this column — bright in upper-mid, fades top and bottom
      const colHeight = auroraBot - auroraTop
      const peakY = auroraTop + colHeight * (0.25 + n1 * 0.2) // peak varies with noise
      const alpha = intensity * 0.10 * brightMult

      const grad = ctx.createLinearGradient(x, auroraTop, x, auroraBot)
      grad.addColorStop(0, `hsla(${hue}, ${sat}%, ${light}%, 0)`)
      grad.addColorStop(Math.max(0.05, (peakY - auroraTop) / colHeight - 0.15),
        `hsla(${hue}, ${sat}%, ${light}%, ${alpha * 0.3})`)
      grad.addColorStop((peakY - auroraTop) / colHeight,
        `hsla(${hue}, ${sat}%, ${light}%, ${alpha})`)
      grad.addColorStop(Math.min(0.95, (peakY - auroraTop) / colHeight + 0.25),
        `hsla(${hue}, ${sat}%, ${light}%, ${alpha * 0.4})`)
      grad.addColorStop(1, `hsla(${hue}, ${sat}%, ${light}%, 0)`)

      ctx.fillStyle = grad
      ctx.fillRect(x, auroraTop, columnStep + 1, colHeight)
    }

    // --- Soft ambient glow beneath aurora ---
    const ambientGrad = ctx.createLinearGradient(0, h * 0.3, 0, h * 0.75)
    ambientGrad.addColorStop(0, `rgba(34, 197, 94, ${0.015 * brightMult})`)
    ambientGrad.addColorStop(1, 'rgba(34, 197, 94, 0)')
    ctx.fillStyle = ambientGrad
    ctx.fillRect(0, h * 0.3, w, h * 0.45)

    // --- Treeline ---
    ctx.fillStyle = '#060810'
    ctx.beginPath()
    ctx.moveTo(0, h)
    for (let i = 0; i < treeline.length; i++) {
      ctx.lineTo(i, treeline[i])
    }
    ctx.lineTo(w, h)
    ctx.closePath()
    ctx.fill()

    // --- Lake reflection (faint mirrored glow) ---
    const lakeY = h * 0.88
    ctx.save()
    ctx.globalAlpha = 0.025 * brightMult
    ctx.beginPath()
    ctx.rect(0, lakeY, w, h - lakeY)
    ctx.clip()

    // Horizontal streaks mirroring aurora colors
    for (let ry = lakeY; ry < h; ry += 3) {
      const ripple = Math.sin(ry * 0.03 + time * 0.25) * 20
      const fade = 1 - (ry - lakeY) / (h - lakeY)
      const rn = noise3D(ry * 0.01, time * 0.05, 50) * 0.5 + 0.5
      const hue = 140 + rn * 40

      ctx.fillStyle = `hsla(${hue}, 50%, 40%, ${fade * 0.6})`
      ctx.fillRect(w * 0.1 + ripple, ry, w * 0.8, 2)
    }
    ctx.restore()

    // --- Faint horizon glow ---
    const horizonGrad = ctx.createRadialGradient(w * 0.5, h * 0.85, 0, w * 0.5, h * 0.85, w * 0.5)
    horizonGrad.addColorStop(0, `rgba(6, 182, 212, ${0.02 * brightMult})`)
    horizonGrad.addColorStop(1, 'rgba(6, 182, 212, 0)')
    ctx.fillStyle = horizonGrad
    ctx.fillRect(0, h * 0.6, w, h * 0.4)
  }

  function handleResize() {
    const info = initSceneCanvas(canvas)
    ctx = info.ctx; w = info.w; h = info.h
    stars = createStars(120, w, h * 0.55)
    generateTreeline()
  }

  onMount(() => {
    const info = initSceneCanvas(canvas)
    ctx = info.ctx; w = info.w; h = info.h
    stars = createStars(120, w, h * 0.55)
    generateTreeline()
    stopLoop = createAnimationLoop(drawFrame)
    window.addEventListener('resize', handleResize)
  })

  onDestroy(() => {
    stopLoop()
    unsub()
    window.removeEventListener('resize', handleResize)
  })
</script>

<canvas bind:this={canvas} class="scene-canvas"></canvas>

<style>
  .scene-canvas {
    position: fixed;
    inset: 0;
    width: 100%;
    height: 100%;
    z-index: 0;
    pointer-events: none;
  }
</style>
