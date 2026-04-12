<script>
  import { onMount, onDestroy } from 'svelte'
  import { sonos } from '$lib/stores/sonos.js'
  import { apiGet } from '$lib/api.js'
  import { initSceneCanvas, createAnimationLoop, createRainDrops, drawRain, createSnowFlakes, drawSnow } from './scene-utils.js'

  /** @type {HTMLCanvasElement} */
  let canvas
  /** @type {CanvasRenderingContext2D} */
  let ctx
  let w = 1920
  let h = 1080
  let stopLoop = () => {}
  let musicPlaying = false

  const unsub = sonos.subscribe(($s) => { musicPlaying = $s.state === 'PLAYING' })

  // Weather state
  let weatherDesc = 'clear'
  let isNight = false
  /** @type {ReturnType<typeof setInterval> | null} */
  let weatherTimer = null

  // Particles
  /** @type {any[]} */
  let rainDrops = []
  /** @type {any[]} */
  let snowFlakes = []
  /** @type {Array<{x:number,y:number,size:number,speed:number}>} */
  let clouds = []
  /** @type {Array<{x:number,y:number,phase:number}>} */
  let stars = []

  // Window glass rain streaks (separate from outside rain)
  /** @type {Array<{x:number,y:number,speed:number,length:number,opacity:number}>} */
  let glassStreaks = []

  // Lightning
  let lightningFlash = 0

  // Steam from mug
  /** @type {Array<{x:number,y:number,age:number,maxAge:number,drift:number}>} */
  let steamParts = []

  // Window geometry
  const WIN = {
    x: 0.52,  // left edge (% of width)
    y: 0.12,  // top edge
    w: 0.38,  // width
    h: 0.72,  // height
    paneW: 2, // divider count horizontal
    paneH: 2, // divider count vertical
    frameW: 8, // frame thickness
    divW: 4,   // divider thickness
  }

  async function fetchWeather() {
    try {
      const data = await apiGet('/api/weather')
      const wx = data?.weather
      if (wx) {
        weatherDesc = (wx.description || 'clear').toLowerCase()
        const icon = wx.icon || ''
        isNight = icon.endsWith('n')
      }
    } catch { /* ignore */ }
  }

  function initWeatherParticles() {
    const winLeft = w * WIN.x
    const winRight = w * (WIN.x + WIN.w)
    const winTop = h * WIN.y
    const winBot = h * (WIN.y + WIN.h)

    if (weatherDesc.includes('rain') || weatherDesc.includes('drizzle') || weatherDesc.includes('thunderstorm')) {
      rainDrops = createRainDrops(120, w * WIN.w, h * WIN.h)
      // Offset to window area
      for (const d of rainDrops) { d.x += winLeft; d.y += winTop }
      // Glass streaks
      glassStreaks = []
      for (let i = 0; i < 30; i++) {
        glassStreaks.push({
          x: winLeft + Math.random() * w * WIN.w,
          y: winTop + Math.random() * h * WIN.h,
          speed: 0.3 + Math.random() * 0.8,
          length: 15 + Math.random() * 40,
          opacity: 0.03 + Math.random() * 0.06,
        })
      }
    } else {
      rainDrops = []
      glassStreaks = []
    }

    if (weatherDesc.includes('snow')) {
      snowFlakes = createSnowFlakes(60, w * WIN.w, h * WIN.h)
      for (const f of snowFlakes) { f.x += winLeft; f.y += winTop }
    } else {
      snowFlakes = []
    }

    // Clouds (always, density varies)
    const cloudCount = weatherDesc.includes('cloud') || weatherDesc.includes('overcast') ? 6 : 3
    clouds = []
    for (let i = 0; i < cloudCount; i++) {
      clouds.push({
        x: winLeft + Math.random() * w * WIN.w * 1.5,
        y: winTop + h * WIN.h * (0.05 + Math.random() * 0.25),
        size: 30 + Math.random() * 50,
        speed: 0.1 + Math.random() * 0.2,
      })
    }

    // Stars (only at night, clear)
    if (isNight && (weatherDesc.includes('clear') || weatherDesc.includes('few clouds'))) {
      stars = []
      for (let i = 0; i < 40; i++) {
        stars.push({
          x: winLeft + Math.random() * w * WIN.w,
          y: winTop + Math.random() * h * WIN.h * 0.5,
          phase: Math.random() * Math.PI * 2,
        })
      }
    } else {
      stars = []
    }
  }

  function getSkyGradient() {
    const now = new Date()
    const hour = now.getHours()

    if (hour >= 6 && hour < 8) {
      // Sunrise
      return ['#1a1a3e', '#3d2060', '#e87d4f', '#f4a63a']
    } else if (hour >= 8 && hour < 17) {
      // Day
      if (weatherDesc.includes('overcast') || weatherDesc.includes('cloud')) {
        return ['#4a5568', '#718096', '#a0aec0']
      }
      return ['#1e3a5f', '#2b6cb0', '#63b3ed']
    } else if (hour >= 17 && hour < 20) {
      // Sunset
      return ['#1a1a3e', '#6b2fa0', '#e87d4f', '#f4a63a']
    } else {
      // Night
      return ['#05050f', '#0a0a20', '#0f1035']
    }
  }

  function drawFrame(time) {
    if (!ctx) return

    // --- Clear ---
    ctx.fillStyle = '#0a0a10'
    ctx.fillRect(0, 0, w, h)

    const wl = w * WIN.x
    const wt = h * WIN.y
    const ww = w * WIN.w
    const wh = h * WIN.h

    // --- Sky through window ---
    ctx.save()
    ctx.beginPath()
    ctx.rect(wl + WIN.frameW, wt + WIN.frameW, ww - WIN.frameW * 2, wh - WIN.frameW * 2)
    ctx.clip()

    const skyColors = getSkyGradient()
    const skyGrad = ctx.createLinearGradient(wl, wt, wl, wt + wh)
    skyColors.forEach((c, i) => skyGrad.addColorStop(i / (skyColors.length - 1), c))
    ctx.fillStyle = skyGrad
    ctx.fillRect(wl, wt, ww, wh)

    // --- Stars ---
    for (const s of stars) {
      const twinkle = Math.sin(time * 1.5 + s.phase) * 0.5 + 0.5
      ctx.fillStyle = `rgba(255, 255, 255, ${0.3 + twinkle * 0.6})`
      ctx.beginPath()
      ctx.arc(s.x, s.y, 1, 0, Math.PI * 2)
      ctx.fill()
    }

    // --- Clouds ---
    for (const c of clouds) {
      c.x -= c.speed
      if (c.x + c.size < wl) c.x = wl + ww + c.size

      const cloudAlpha = weatherDesc.includes('overcast') ? 0.4 : 0.2
      ctx.fillStyle = `rgba(200, 210, 220, ${cloudAlpha})`
      // Simple cloud shape: overlapping circles
      for (let j = 0; j < 3; j++) {
        ctx.beginPath()
        ctx.arc(c.x + j * c.size * 0.35, c.y + Math.sin(j) * 5, c.size * 0.3, 0, Math.PI * 2)
        ctx.fill()
      }
    }

    // --- Outside rain ---
    if (rainDrops.length) {
      drawRain(ctx, w, h, rainDrops, musicPlaying ? 1.2 : 1.0)
      // Re-seed drops that went below window
      for (const d of rainDrops) {
        if (d.y > wt + wh) { d.y = wt - d.length; d.x = wl + Math.random() * ww }
      }
    }

    // --- Snow ---
    if (snowFlakes.length) {
      drawSnow(ctx, w, h, snowFlakes, time)
      for (const f of snowFlakes) {
        if (f.y > wt + wh) { f.y = wt - f.size; f.x = wl + Math.random() * ww }
      }
    }

    // --- Lightning flash ---
    if (weatherDesc.includes('thunderstorm') && lightningFlash <= 0 && Math.random() < 0.003) {
      lightningFlash = 3
    }
    if (lightningFlash > 0) {
      ctx.fillStyle = `rgba(255, 255, 240, ${lightningFlash * 0.1})`
      ctx.fillRect(wl, wt, ww, wh)
      lightningFlash -= 1
    }

    ctx.restore() // un-clip

    // --- Glass rain streaks (on top of window, inside the glass) ---
    for (const s of glassStreaks) {
      s.y += s.speed
      if (s.y > wt + wh) { s.y = wt; s.x = wl + Math.random() * ww }
      ctx.strokeStyle = `rgba(150, 180, 220, ${s.opacity})`
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(s.x, s.y)
      ctx.lineTo(s.x, s.y + s.length)
      ctx.stroke()
    }

    // --- Window frame ---
    ctx.fillStyle = '#1a1a25'
    // Outer frame
    ctx.fillRect(wl, wt, ww, WIN.frameW) // top
    ctx.fillRect(wl, wt + wh - WIN.frameW, ww, WIN.frameW) // bottom
    ctx.fillRect(wl, wt, WIN.frameW, wh) // left
    ctx.fillRect(wl + ww - WIN.frameW, wt, WIN.frameW, wh) // right
    // Dividers
    const midX = wl + ww / 2
    const midY = wt + wh / 2
    ctx.fillRect(midX - WIN.divW / 2, wt, WIN.divW, wh) // vertical
    ctx.fillRect(wl, midY - WIN.divW / 2, ww, WIN.divW) // horizontal

    // --- Window sill ---
    ctx.fillStyle = '#1f1f2e'
    ctx.fillRect(wl - 10, wt + wh, ww + 20, 12)

    // --- Mug on sill ---
    const mugX = wl + ww * 0.7
    const mugY = wt + wh - 2
    ctx.fillStyle = '#2a2a3a'
    ctx.fillRect(mugX, mugY - 14, 12, 14)
    ctx.fillRect(mugX - 1, mugY - 15, 14, 2)
    // Handle
    ctx.strokeStyle = '#2a2a3a'
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.arc(mugX + 13, mugY - 8, 4, -Math.PI * 0.5, Math.PI * 0.5)
    ctx.stroke()

    // --- Steam from mug ---
    if (steamParts.length < 6) {
      steamParts.push({
        x: mugX + 6, y: mugY - 16,
        age: 0, maxAge: 60 + Math.random() * 40,
        drift: Math.random() * 2 - 1,
      })
    }
    for (let i = steamParts.length - 1; i >= 0; i--) {
      const sp = steamParts[i]
      sp.age += musicPlaying ? 1.2 : 1
      sp.y -= 0.4
      sp.x += Math.sin(sp.age * 0.08 + sp.drift) * 0.3
      if (sp.age > sp.maxAge) { steamParts.splice(i, 1); continue }
      const alpha = (1 - sp.age / sp.maxAge) * 0.15
      ctx.strokeStyle = `rgba(200, 200, 220, ${alpha})`
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(sp.x, sp.y)
      ctx.quadraticCurveTo(sp.x + Math.sin(sp.age * 0.1) * 3, sp.y - 3, sp.x + sp.drift, sp.y - 6)
      ctx.stroke()
    }

    // --- Plant on sill ---
    const plantX = wl + ww * 0.2
    const plantY = wt + wh
    ctx.fillStyle = '#1a2a1a'
    ctx.fillRect(plantX, plantY - 10, 10, 10) // pot
    ctx.fillStyle = '#2d5a2d'
    // Leaves (simple triangles)
    ctx.beginPath()
    ctx.moveTo(plantX + 5, plantY - 22)
    ctx.lineTo(plantX - 2, plantY - 10)
    ctx.lineTo(plantX + 12, plantY - 10)
    ctx.fill()
    ctx.beginPath()
    ctx.moveTo(plantX + 2, plantY - 18)
    ctx.lineTo(plantX - 5, plantY - 10)
    ctx.lineTo(plantX + 5, plantY - 10)
    ctx.fill()

    // --- Warm light spill from window ---
    const lightGrad = ctx.createRadialGradient(wl + ww / 2, wt + wh * 0.6, 0, wl + ww / 2, wt + wh * 0.6, ww * 0.8)
    lightGrad.addColorStop(0, 'rgba(249, 168, 37, 0.04)')
    lightGrad.addColorStop(1, 'rgba(249, 168, 37, 0)')
    ctx.fillStyle = lightGrad
    ctx.fillRect(0, 0, w, h)

    // --- Subtle lamp glow in room (bottom left area) ---
    const lampGrad = ctx.createRadialGradient(w * 0.15, h * 0.85, 0, w * 0.15, h * 0.85, w * 0.2)
    lampGrad.addColorStop(0, 'rgba(251, 191, 36, 0.03)')
    lampGrad.addColorStop(1, 'rgba(251, 191, 36, 0)')
    ctx.fillStyle = lampGrad
    ctx.fillRect(0, 0, w, h)
  }

  onMount(async () => {
    const info = initSceneCanvas(canvas)
    ctx = info.ctx
    w = info.w
    h = info.h

    await fetchWeather()
    initWeatherParticles()
    weatherTimer = setInterval(async () => {
      await fetchWeather()
      initWeatherParticles()
    }, 600_000) // 10 minutes

    stopLoop = createAnimationLoop(drawFrame)

    const onResize = () => {
      const info = initSceneCanvas(canvas)
      ctx = info.ctx
      w = info.w
      h = info.h
      initWeatherParticles()
    }
    window.addEventListener('resize', onResize)
  })

  onDestroy(() => {
    stopLoop()
    unsub()
    if (weatherTimer) clearInterval(weatherTimer)
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
