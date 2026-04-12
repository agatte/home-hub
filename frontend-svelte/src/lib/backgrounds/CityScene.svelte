<script>
  import { onMount, onDestroy } from 'svelte'
  import { sonos } from '$lib/stores/sonos.js'
  import { apiGet } from '$lib/api.js'
  import { createAnimationLoop } from './scene-utils.js'

  /** @type {HTMLCanvasElement} */
  let canvas
  /** @type {HTMLCanvasElement} */
  let pixelCanvas
  let stopLoop = () => {}
  let musicPlaying = false

  const unsub = sonos.subscribe(($s) => { musicPlaying = $s.state === 'PLAYING' })

  const PW = 480
  const PH = 270
  const GROUND_Y = PH - 20

  // Weather
  let weatherDesc = 'clear'
  /** @type {ReturnType<typeof setInterval> | null} */
  let weatherTimer = null

  // --- City elements (generated once, deterministic) ---

  /** @typedef {{x:number, w:number, h:number, baseColor:string, roofStyle:string, windows:Array<{wx:number,wy:number,on:boolean,flicker:number}>, hasAntenna:boolean, hasTank:boolean, depth:number}} Building */
  /** @type {Building[]} */
  let farBuildings = []
  /** @type {Building[]} */
  let nearBuildings = []

  /** @type {Array<{x:number,y:number,w:number,speed:number,opacity:number}>} */
  let clouds = []
  /** @type {Array<{x:number,y:number,w:number,h:number,speed:number,color:string}>} */
  let cars = []
  /** @type {Array<{x:number,y:number,speed:number}>} */
  let precipitation = []
  /** @type {Array<{x:number,y:number,phase:number}>} */
  let stars = []

  async function fetchWeather() {
    try {
      const data = await apiGet('/api/weather')
      if (data?.weather) weatherDesc = (data.weather.description || 'clear').toLowerCase()
    } catch { /* ignore */ }
  }

  function getSkyColors() {
    const hour = new Date().getHours()
    const rainy = weatherDesc.includes('rain') || weatherDesc.includes('drizzle') || weatherDesc.includes('thunderstorm')
    const overcast = weatherDesc.includes('cloud') || weatherDesc.includes('overcast')

    if (rainy) return ['#101018', '#181825', '#1e1e30']
    if (hour >= 6 && hour < 8) return ['#0f0820', '#2a1040', '#804030', '#d08040']
    if (hour >= 8 && hour < 17) {
      if (overcast) return ['#252535', '#35354a', '#454560']
      return ['#0f2040', '#1a3560', '#2a5585']
    }
    if (hour >= 17 && hour < 20) return ['#0f0825', '#3a1555', '#a05535', '#d09040']
    return ['#030308', '#06060f', '#0a0a18']
  }

  /** @param {string} roofStyle */
  function seededRandom(seed) {
    let s = seed
    return () => { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646 }
  }

  function generateBuildings() {
    // Far layer (shorter, darker, behind)
    farBuildings = []
    let rng = seededRandom(42)
    const farColors = ['#0a0a14', '#0c0c18', '#0e0e1c']
    let bx = -5
    while (bx < PW + 10) {
      const bw = 10 + Math.floor(rng() * 22)
      const bh = 25 + Math.floor(rng() * 50)
      farBuildings.push({
        x: bx, w: bw, h: bh, depth: 0,
        baseColor: farColors[Math.floor(rng() * farColors.length)],
        roofStyle: 'flat',
        windows: [], hasAntenna: false, hasTank: false,
      })
      bx += bw + Math.floor(rng() * 4)
    }

    // Near layer (taller, more detail)
    nearBuildings = []
    rng = seededRandom(137)
    const nearColors = ['#10101e', '#131325', '#161630', '#12122a', '#0f0f20']
    const roofStyles = ['flat', 'pointed', 'stepped', 'rounded']
    bx = -3
    while (bx < PW + 5) {
      const bw = 14 + Math.floor(rng() * 20)
      const bh = 50 + Math.floor(rng() * 90)
      const color = nearColors[Math.floor(rng() * nearColors.length)]
      const roof = roofStyles[Math.floor(rng() * roofStyles.length)]

      const windows = []
      const winSX = 4
      const winSY = 6
      for (let wx = 3; wx < bw - 3; wx += winSX) {
        for (let wy = 6; wy < bh - 5; wy += winSY) {
          windows.push({ wx, wy, on: rng() > 0.35, flicker: rng() * Math.PI * 2 })
        }
      }

      nearBuildings.push({
        x: bx, w: bw, h: bh, depth: 1,
        baseColor: color, roofStyle: roof, windows,
        hasAntenna: bh > 100 && rng() > 0.5,
        hasTank: bw > 18 && rng() > 0.6,
      })
      bx += bw + Math.floor(rng() * 3) + 1
    }
  }

  function initDynamic() {
    const overcast = weatherDesc.includes('cloud') || weatherDesc.includes('overcast')
    const rainy = weatherDesc.includes('rain') || weatherDesc.includes('drizzle') || weatherDesc.includes('thunderstorm')
    const snowy = weatherDesc.includes('snow')
    const hour = new Date().getHours()

    // Clouds
    clouds = []
    const cCount = rainy ? 10 : overcast ? 8 : 4
    for (let i = 0; i < cCount; i++) {
      clouds.push({
        x: Math.floor(Math.random() * PW * 1.5),
        y: 6 + Math.floor(Math.random() * 35),
        w: 15 + Math.floor(Math.random() * 35),
        speed: 0.05 + Math.random() * 0.12,
        opacity: rainy ? 0.5 : overcast ? 0.4 : 0.2,
      })
    }

    // Cars
    const carColors = ['#c0392b', '#2980b9', '#d4a017', '#27ae60', '#d35400', '#8e44ad', '#ecf0f1']
    cars = []
    for (let i = 0; i < 6; i++) {
      const dir = i % 2 === 0 ? 1 : -1
      cars.push({
        x: Math.floor(Math.random() * PW),
        y: GROUND_Y + 4 + (dir > 0 ? 0 : 5),
        w: 5 + Math.floor(Math.random() * 3),
        h: 3,
        speed: (0.15 + Math.random() * 0.25) * dir,
        color: carColors[Math.floor(Math.random() * carColors.length)],
      })
    }

    // Precipitation
    precipitation = []
    if (rainy) {
      for (let i = 0; i < 80; i++) {
        precipitation.push({ x: Math.floor(Math.random() * PW), y: Math.floor(Math.random() * PH), speed: 2 + Math.random() * 3 })
      }
    } else if (snowy) {
      for (let i = 0; i < 40; i++) {
        precipitation.push({ x: Math.floor(Math.random() * PW), y: Math.floor(Math.random() * PH), speed: 0.2 + Math.random() * 0.4 })
      }
    }

    // Stars
    stars = []
    if (hour >= 20 || hour < 6) {
      for (let i = 0; i < 50; i++) {
        stars.push({ x: Math.floor(Math.random() * PW), y: Math.floor(Math.random() * PH * 0.25), phase: Math.random() * Math.PI * 2 })
      }
    }
  }

  /** @param {CanvasRenderingContext2D} pctx @param {Building} b */
  function drawBuilding(pctx, b, time) {
    const by = GROUND_Y - b.h

    // Main body
    pctx.fillStyle = b.baseColor
    pctx.fillRect(b.x, by, b.w, b.h)

    // Slightly lighter edge (depth illusion)
    if (b.depth > 0) {
      pctx.fillStyle = 'rgba(255,255,255,0.02)'
      pctx.fillRect(b.x, by, 1, b.h)
    }

    // Roof variations
    if (b.roofStyle === 'pointed' && b.depth > 0) {
      pctx.fillStyle = b.baseColor
      const peakH = Math.min(8, b.w / 2)
      for (let i = 0; i < peakH; i++) {
        const indent = Math.floor((i / peakH) * (b.w / 2))
        pctx.fillRect(b.x + indent, by - i - 1, b.w - indent * 2, 1)
      }
    } else if (b.roofStyle === 'stepped' && b.depth > 0 && b.w > 16) {
      pctx.fillStyle = b.baseColor
      pctx.fillRect(b.x + 2, by - 4, b.w - 4, 4)
      pctx.fillRect(b.x + 5, by - 7, b.w - 10, 3)
    } else if (b.roofStyle === 'rounded' && b.depth > 0) {
      pctx.fillStyle = b.baseColor
      const r = Math.min(4, b.w / 3)
      for (let i = 0; i < r; i++) {
        const shrink = Math.floor(Math.sqrt(r * r - (r - i) * (r - i)))
        pctx.fillRect(b.x + (b.w / 2) - shrink, by - i - 1, shrink * 2, 1)
      }
    }

    // Antenna
    if (b.hasAntenna) {
      const ax = b.x + Math.floor(b.w / 2)
      pctx.fillStyle = '#1a1a2a'
      pctx.fillRect(ax, by - 8, 1, 8)
      // Blinking red light
      if (Math.sin(time * 2) > 0) {
        pctx.fillStyle = '#ff2020'
        pctx.fillRect(ax, by - 9, 1, 1)
      }
    }

    // Water tank
    if (b.hasTank) {
      const tx = b.x + b.w - 8
      pctx.fillStyle = '#151520'
      pctx.fillRect(tx, by - 3, 5, 3)
      pctx.fillRect(tx + 1, by - 6, 1, 3) // legs
      pctx.fillRect(tx + 3, by - 6, 1, 3)
    }

    // Windows
    for (const win of b.windows) {
      if (musicPlaying && Math.random() < 0.002) win.on = !win.on
      if (!win.on) continue

      const winAlpha = 0.5 + Math.sin(time * 0.4 + win.flicker) * 0.1
      // Warm yellow with slight color variation
      const warmth = 180 + Math.floor(win.flicker * 10) % 40
      pctx.fillStyle = `rgba(255, ${warmth}, 80, ${winAlpha})`
      pctx.fillRect(b.x + win.wx, by + win.wy, 2, 2)
    }
  }

  function drawFrame(time) {
    if (!pixelCanvas) return
    const pctx = pixelCanvas.getContext('2d')
    if (!pctx) return

    const speedMult = musicPlaying ? 1.3 : 1.0

    // --- Sky gradient ---
    const skyColors = getSkyColors()
    const skyGrad = pctx.createLinearGradient(0, 0, 0, PH * 0.7)
    skyColors.forEach((c, i) => skyGrad.addColorStop(i / (skyColors.length - 1), c))
    pctx.fillStyle = skyGrad
    pctx.fillRect(0, 0, PW, PH)

    // --- Stars ---
    for (const s of stars) {
      const twinkle = Math.sin(time * 1.5 + s.phase) * 0.5 + 0.5
      if (twinkle > 0.25) {
        pctx.fillStyle = `rgba(255, 255, 255, ${twinkle * 0.7})`
        pctx.fillRect(s.x, s.y, 1, 1)
      }
    }

    // --- Clouds ---
    for (const c of clouds) {
      c.x -= c.speed * speedMult
      if (c.x + c.w < -5) c.x = PW + c.w + 5

      pctx.fillStyle = `rgba(140, 150, 165, ${c.opacity})`
      // Pixel cloud shape: layered bumps
      const cx = Math.floor(c.x)
      const cy = Math.floor(c.y)
      pctx.fillRect(cx + 2, cy, c.w - 4, 4)
      pctx.fillRect(cx, cy + 2, c.w, 3)
      pctx.fillRect(cx + Math.floor(c.w * 0.1), cy - 2, Math.floor(c.w * 0.35), 3)
      pctx.fillRect(cx + Math.floor(c.w * 0.4), cy - 3, Math.floor(c.w * 0.4), 4)
    }

    // --- Atmospheric haze behind far buildings ---
    const hazeGrad = pctx.createLinearGradient(0, PH * 0.3, 0, GROUND_Y)
    hazeGrad.addColorStop(0, 'rgba(15, 15, 30, 0)')
    hazeGrad.addColorStop(1, 'rgba(15, 15, 30, 0.3)')
    pctx.fillStyle = hazeGrad
    pctx.fillRect(0, PH * 0.3, PW, GROUND_Y - PH * 0.3)

    // --- Far buildings (background layer) ---
    for (const b of farBuildings) drawBuilding(pctx, b, time)

    // --- City glow between layers (atmospheric depth) ---
    const glowGrad = pctx.createLinearGradient(0, GROUND_Y - 60, 0, GROUND_Y)
    glowGrad.addColorStop(0, 'rgba(20, 18, 35, 0)')
    glowGrad.addColorStop(0.5, 'rgba(25, 22, 45, 0.15)')
    glowGrad.addColorStop(1, 'rgba(30, 25, 50, 0.25)')
    pctx.fillStyle = glowGrad
    pctx.fillRect(0, GROUND_Y - 60, PW, 60)

    // --- Near buildings (foreground layer) ---
    for (const b of nearBuildings) drawBuilding(pctx, b, time)

    // --- Ambient glow from lit areas (warm spots below window clusters) ---
    for (const b of nearBuildings) {
      if (b.h > 70) {
        const litWindows = b.windows.filter(w => w.on).length
        if (litWindows > 5) {
          pctx.fillStyle = `rgba(255, 200, 100, ${0.01 * Math.min(litWindows, 15)})`
          pctx.fillRect(b.x - 2, GROUND_Y - b.h, b.w + 4, b.h + 5)
        }
      }
    }

    // --- Street ---
    pctx.fillStyle = '#08080f'
    pctx.fillRect(0, GROUND_Y, PW, PH - GROUND_Y)

    // Sidewalk
    pctx.fillStyle = '#101018'
    pctx.fillRect(0, GROUND_Y, PW, 2)

    // Road markings
    pctx.fillStyle = '#1a1a28'
    for (let dx = 0; dx < PW; dx += 12) {
      pctx.fillRect(dx, GROUND_Y + 9, 6, 1)
    }

    // --- Streetlamp glow on ground ---
    for (let lx = 25; lx < PW; lx += 55) {
      pctx.fillStyle = '#14141e'
      pctx.fillRect(lx, GROUND_Y - 14, 1, 14)
      pctx.fillRect(lx - 1, GROUND_Y - 14, 3, 1)
      // Light cone
      pctx.fillStyle = 'rgba(255, 210, 120, 0.06)'
      pctx.fillRect(lx - 4, GROUND_Y - 12, 9, 14)
      pctx.fillStyle = 'rgba(255, 210, 120, 0.03)'
      pctx.fillRect(lx - 7, GROUND_Y - 10, 15, 12)
    }

    // --- Cars ---
    for (const car of cars) {
      car.x += car.speed * speedMult
      if (car.speed > 0 && car.x > PW + 10) car.x = -car.w - 5
      if (car.speed < 0 && car.x < -car.w - 10) car.x = PW + 5

      const cx = Math.floor(car.x)
      // Car body
      pctx.fillStyle = car.color
      pctx.fillRect(cx, car.y, car.w, car.h)
      // Cabin (slightly inset and lighter)
      pctx.fillStyle = 'rgba(80, 90, 110, 0.4)'
      pctx.fillRect(cx + 1, car.y - 1, car.w - 2, 1)
      // Headlights
      const hlX = car.speed > 0 ? cx + car.w : cx - 1
      pctx.fillStyle = 'rgba(255, 240, 200, 0.5)'
      pctx.fillRect(hlX, car.y, 1, 1)
      // Taillights
      const tlX = car.speed > 0 ? cx : cx + car.w - 1
      pctx.fillStyle = 'rgba(255, 50, 50, 0.4)'
      pctx.fillRect(tlX, car.y + car.h - 1, 1, 1)
    }

    // --- Precipitation ---
    const isSnow = weatherDesc.includes('snow')
    for (const p of precipitation) {
      p.y += p.speed * speedMult
      if (isSnow) p.x += Math.sin(time + p.x * 0.08) * 0.2
      if (p.y > PH) { p.y = -2; p.x = Math.floor(Math.random() * PW) }

      if (isSnow) {
        pctx.fillStyle = 'rgba(220, 225, 235, 0.5)'
        pctx.fillRect(Math.floor(p.x), Math.floor(p.y), 1, 1)
      } else {
        pctx.fillStyle = 'rgba(120, 150, 200, 0.25)'
        pctx.fillRect(Math.floor(p.x), Math.floor(p.y), 1, 2)
      }
    }

    // --- Lightning ---
    if (weatherDesc.includes('thunderstorm') && Math.random() < 0.003) {
      pctx.fillStyle = 'rgba(200, 200, 240, 0.15)'
      pctx.fillRect(0, 0, PW, PH)
    }

    // --- Scale to main canvas ---
    if (!canvas) return
    const mainCtx = canvas.getContext('2d')
    if (!mainCtx) return
    mainCtx.imageSmoothingEnabled = false
    mainCtx.drawImage(pixelCanvas, 0, 0, canvas.width, canvas.height)
  }

  onMount(async () => {
    canvas.width = canvas.clientWidth
    canvas.height = canvas.clientHeight
    pixelCanvas = document.createElement('canvas')
    pixelCanvas.width = PW
    pixelCanvas.height = PH

    generateBuildings()
    await fetchWeather()
    initDynamic()

    weatherTimer = setInterval(async () => {
      await fetchWeather()
      initDynamic()
    }, 600_000)

    stopLoop = createAnimationLoop(drawFrame)
    const onResize = () => { canvas.width = canvas.clientWidth; canvas.height = canvas.clientHeight }
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
