<script>
  import { onMount, onDestroy } from 'svelte'
  import { sonos } from '$lib/stores/sonos.js'
  import { initSceneCanvas, createAnimationLoop, createRainDrops, drawRain } from './scene-utils.js'

  /** @type {HTMLCanvasElement} */
  let canvas
  /** @type {CanvasRenderingContext2D} */
  let ctx
  let w = 1920
  let h = 1080
  let stopLoop = () => {}
  let musicPlaying = false

  const unsub = sonos.subscribe(($s) => { musicPlaying = $s.state === 'PLAYING' })

  // Rain (always active in relax — lo-fi aesthetic)
  /** @type {any[]} */
  let rainDrops = []
  /** @type {Array<{x:number,y:number,speed:number,length:number,opacity:number}>} */
  let glassStreaks = []

  // Steam particles from coffee
  /** @type {Array<{x:number,y:number,age:number,maxAge:number,drift:number}>} */
  let steamParts = []

  // Cat tail animation
  let catTailAngle = 0

  // Lamp glow pulse
  let lampPulse = 0

  // Room layout constants (proportional to canvas)
  function layout() {
    return {
      // Window (upper right area)
      winX: w * 0.6, winY: h * 0.08, winW: w * 0.32, winH: h * 0.5,
      // Desk (lower center-right)
      deskX: w * 0.45, deskY: h * 0.7, deskW: w * 0.45, deskH: 8,
      // Lamp (on desk, left side)
      lampX: w * 0.52, lampY: h * 0.45,
      // Mug (on desk, center)
      mugX: w * 0.65, mugY: h * 0.7,
      // Cat (on window sill)
      catX: w * 0.72, catY: h * 0.08 + h * 0.5 - 18,
      // Bookshelf (left wall)
      shelfX: w * 0.05, shelfY: h * 0.15, shelfW: w * 0.15, shelfH: h * 0.55,
    }
  }

  function initRain() {
    const l = layout()
    // Rain outside window
    rainDrops = createRainDrops(80, l.winW, l.winH)
    for (const d of rainDrops) { d.x += l.winX; d.y += l.winY }
    // Glass streaks
    glassStreaks = []
    for (let i = 0; i < 20; i++) {
      glassStreaks.push({
        x: l.winX + Math.random() * l.winW,
        y: l.winY + Math.random() * l.winH,
        speed: 0.2 + Math.random() * 0.5,
        length: 10 + Math.random() * 30,
        opacity: 0.02 + Math.random() * 0.04,
      })
    }
  }

  function drawFrame(time) {
    if (!ctx) return
    const l = layout()

    // --- Room background (very dark warm) ---
    ctx.fillStyle = '#0d0a08'
    ctx.fillRect(0, 0, w, h)

    // --- Bookshelf (left wall) ---
    ctx.fillStyle = '#151210'
    ctx.fillRect(l.shelfX, l.shelfY, l.shelfW, l.shelfH)
    // Shelf dividers
    const shelfCount = 4
    for (let i = 0; i <= shelfCount; i++) {
      const sy = l.shelfY + (l.shelfH / shelfCount) * i
      ctx.fillStyle = '#1a1614'
      ctx.fillRect(l.shelfX, sy - 2, l.shelfW, 4)
    }
    // Books (colored rectangles on shelves)
    const bookColors = ['#2d1b1b', '#1b2d1b', '#1b1b2d', '#2d2d1b', '#2d1b2d', '#1b2d2d']
    for (let shelf = 0; shelf < shelfCount; shelf++) {
      const sy = l.shelfY + (l.shelfH / shelfCount) * shelf + 6
      const shelfHeight = l.shelfH / shelfCount - 10
      let bx = l.shelfX + 4
      for (let b = 0; b < 6 + Math.floor(Math.random() * 0.01); b++) {
        const bw = 6 + (shelf * 3 + b * 7) % 8 // deterministic widths
        const bh = shelfHeight * (0.6 + ((shelf * 5 + b * 3) % 4) * 0.1)
        if (bx + bw > l.shelfX + l.shelfW - 4) break
        ctx.fillStyle = bookColors[(shelf * 3 + b) % bookColors.length]
        ctx.fillRect(bx, sy + shelfHeight - bh, bw, bh)
        bx += bw + 2
      }
    }

    // --- Window (cool blue, rain) ---
    // Window opening
    ctx.fillStyle = '#0f1a2e'
    ctx.fillRect(l.winX, l.winY, l.winW, l.winH)

    // Night sky through window
    const skyGrad = ctx.createLinearGradient(l.winX, l.winY, l.winX, l.winY + l.winH)
    skyGrad.addColorStop(0, '#05080f')
    skyGrad.addColorStop(0.6, '#0f1a30')
    skyGrad.addColorStop(1, '#1a2a45')
    ctx.fillStyle = skyGrad
    ctx.fillRect(l.winX, l.winY, l.winW, l.winH)

    // Rain outside window
    ctx.save()
    ctx.beginPath()
    ctx.rect(l.winX, l.winY, l.winW, l.winH)
    ctx.clip()
    drawRain(ctx, w, h, rainDrops, musicPlaying ? 1.3 : 1.0, '#4a7aaa')
    for (const d of rainDrops) {
      if (d.y > l.winY + l.winH) { d.y = l.winY - d.length; d.x = l.winX + Math.random() * l.winW }
    }
    ctx.restore()

    // Glass streaks
    for (const s of glassStreaks) {
      s.y += s.speed
      if (s.y > l.winY + l.winH) { s.y = l.winY; s.x = l.winX + Math.random() * l.winW }
      ctx.strokeStyle = `rgba(100, 140, 180, ${s.opacity})`
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(s.x, s.y)
      ctx.lineTo(s.x, s.y + s.length)
      ctx.stroke()
    }

    // Window frame
    ctx.fillStyle = '#1a1815'
    const wf = 6
    ctx.fillRect(l.winX, l.winY, l.winW, wf)
    ctx.fillRect(l.winX, l.winY + l.winH - wf, l.winW, wf)
    ctx.fillRect(l.winX, l.winY, wf, l.winH)
    ctx.fillRect(l.winX + l.winW - wf, l.winY, wf, l.winH)
    // Dividers
    ctx.fillRect(l.winX + l.winW / 2 - 2, l.winY, 4, l.winH)
    ctx.fillRect(l.winX, l.winY + l.winH / 2 - 2, l.winW, 4)

    // Window sill
    ctx.fillStyle = '#1f1c18'
    ctx.fillRect(l.winX - 8, l.winY + l.winH, l.winW + 16, 8)

    // --- Desk ---
    ctx.fillStyle = '#1a1614'
    ctx.fillRect(l.deskX, l.deskY, l.deskW, l.deskH)
    // Desk legs
    ctx.fillRect(l.deskX + 10, l.deskY + l.deskH, 6, h - l.deskY - l.deskH)
    ctx.fillRect(l.deskX + l.deskW - 16, l.deskY + l.deskH, 6, h - l.deskY - l.deskH)

    // --- Lamp ---
    // Lamp base
    ctx.fillStyle = '#2a2520'
    ctx.fillRect(l.lampX - 3, l.deskY - 6, 14, 6)
    // Lamp pole
    ctx.fillStyle = '#3a3530'
    ctx.fillRect(l.lampX + 3, l.lampY, 2, l.deskY - l.lampY - 6)
    // Lamp shade
    ctx.fillStyle = '#3d3428'
    ctx.beginPath()
    ctx.moveTo(l.lampX - 15, l.lampY)
    ctx.lineTo(l.lampX + 23, l.lampY)
    ctx.lineTo(l.lampX + 18, l.lampY - 20)
    ctx.lineTo(l.lampX - 10, l.lampY - 20)
    ctx.closePath()
    ctx.fill()

    // Lamp glow (the key visual — warm radial glow)
    lampPulse += musicPlaying ? 0.08 : 0.03
    const pulseVal = musicPlaying ? Math.sin(lampPulse) * 0.008 + 0.045 : 0.04
    const glowR = Math.min(w, h) * 0.5
    const lampGlow = ctx.createRadialGradient(l.lampX + 4, l.lampY - 5, 0, l.lampX + 4, l.lampY, glowR)
    lampGlow.addColorStop(0, `rgba(251, 191, 36, ${pulseVal * 2.5})`)
    lampGlow.addColorStop(0.2, `rgba(249, 115, 22, ${pulseVal * 1.2})`)
    lampGlow.addColorStop(0.5, `rgba(249, 115, 22, ${pulseVal * 0.4})`)
    lampGlow.addColorStop(1, 'rgba(249, 115, 22, 0)')
    ctx.fillStyle = lampGlow
    ctx.fillRect(0, 0, w, h)

    // Warm light on desk surface
    const deskGlow = ctx.createRadialGradient(l.lampX, l.deskY, 0, l.lampX, l.deskY, w * 0.25)
    deskGlow.addColorStop(0, 'rgba(251, 191, 36, 0.06)')
    deskGlow.addColorStop(1, 'rgba(251, 191, 36, 0)')
    ctx.fillStyle = deskGlow
    ctx.fillRect(l.deskX, l.deskY - 5, l.deskW, 10)

    // --- Coffee mug ---
    ctx.fillStyle = '#2a2420'
    ctx.fillRect(l.mugX, l.mugY - 16, 14, 16)
    ctx.fillRect(l.mugX - 1, l.mugY - 17, 16, 2)
    // Handle
    ctx.strokeStyle = '#2a2420'
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.arc(l.mugX + 15, l.mugY - 9, 5, -Math.PI * 0.5, Math.PI * 0.5)
    ctx.stroke()

    // --- Steam ---
    if (steamParts.length < 8) {
      steamParts.push({
        x: l.mugX + 7,
        y: l.mugY - 18,
        age: 0,
        maxAge: 50 + Math.random() * 40,
        drift: Math.random() * 3 - 1.5,
      })
    }
    for (let i = steamParts.length - 1; i >= 0; i--) {
      const sp = steamParts[i]
      sp.age += musicPlaying ? 1.3 : 1
      sp.y -= 0.5
      sp.x += Math.sin(sp.age * 0.06 + sp.drift) * 0.4
      if (sp.age > sp.maxAge) { steamParts.splice(i, 1); continue }
      const alpha = (1 - sp.age / sp.maxAge) * 0.12
      ctx.strokeStyle = `rgba(220, 210, 200, ${alpha})`
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.moveTo(sp.x, sp.y)
      ctx.quadraticCurveTo(
        sp.x + Math.sin(sp.age * 0.08) * 4,
        sp.y - 4,
        sp.x + sp.drift * 0.5,
        sp.y - 8,
      )
      ctx.stroke()
    }

    // --- Cat silhouette on window sill ---
    const cx = l.catX
    const cy = l.catY
    ctx.fillStyle = '#12100e'
    // Body (oval)
    ctx.beginPath()
    ctx.ellipse(cx, cy, 14, 10, 0, 0, Math.PI * 2)
    ctx.fill()
    // Head
    ctx.beginPath()
    ctx.arc(cx + 12, cy - 6, 7, 0, Math.PI * 2)
    ctx.fill()
    // Ears
    ctx.beginPath()
    ctx.moveTo(cx + 8, cy - 12)
    ctx.lineTo(cx + 11, cy - 18)
    ctx.lineTo(cx + 14, cy - 12)
    ctx.fill()
    ctx.beginPath()
    ctx.moveTo(cx + 14, cy - 12)
    ctx.lineTo(cx + 17, cy - 18)
    ctx.lineTo(cx + 20, cy - 12)
    ctx.fill()
    // Tail (gentle sway)
    catTailAngle += 0.03
    const tailSway = Math.sin(catTailAngle) * 8
    ctx.strokeStyle = '#12100e'
    ctx.lineWidth = 3
    ctx.lineCap = 'round'
    ctx.beginPath()
    ctx.moveTo(cx - 13, cy + 2)
    ctx.quadraticCurveTo(cx - 22, cy - 5, cx - 25 + tailSway, cy - 15)
    ctx.stroke()

    // --- Floor line ---
    ctx.fillStyle = '#141210'
    ctx.fillRect(0, h * 0.92, w, h * 0.08)
    ctx.fillStyle = '#1a1614'
    ctx.fillRect(0, h * 0.92, w, 2)
  }

  onMount(() => {
    const info = initSceneCanvas(canvas)
    ctx = info.ctx
    w = info.w
    h = info.h
    initRain()
    stopLoop = createAnimationLoop(drawFrame)

    const onResize = () => {
      const info = initSceneCanvas(canvas)
      ctx = info.ctx
      w = info.w
      h = info.h
      initRain()
    }
    window.addEventListener('resize', onResize)
  })

  onDestroy(() => {
    stopLoop()
    unsub()
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
