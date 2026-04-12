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

  // Weather
  let weatherDesc = 'clear'
  let isNight = false
  /** @type {ReturnType<typeof setInterval> | null} */
  let weatherTimer = null

  // Buildings (generated once)
  /** @type {Array<{x:number, w:number, h:number, color:string, windows:Array<{wx:number,wy:number,on:boolean,flicker:number}>}>} */
  let buildings = []

  // Clouds
  /** @type {Array<{x:number,y:number,w:number,speed:number}>} */
  let clouds = []

  // Cars
  /** @type {Array<{x:number,y:number,w:number,h:number,speed:number,color:string}>} */
  let cars = []

  // Stars (for night)
  /** @type {Array<{x:number,y:number,phase:number}>} */
  let stars = []

  // Rain/snow
  /** @type {Array<{x:number,y:number,speed:number}>} */
  let precipitation = []

  // Streetlamps
  /** @type {Array<{x:number}>} */
  let lamps = []

  async function fetchWeather() {
    try {
      const data = await apiGet('/api/weather')
      const wx = data?.weather
      if (wx) {
        weatherDesc = (wx.description || 'clear').toLowerCase()
        isNight = (wx.icon || '').endsWith('n')
      }
    } catch { /* ignore */ }
  }

  function getSkyColors() {
    const hour = new Date().getHours()
    const overcast = weatherDesc.includes('cloud') || weatherDesc.includes('overcast')
    const rainy = weatherDesc.includes('rain') || weatherDesc.includes('drizzle') || weatherDesc.includes('thunderstorm')

    if (rainy) return ['#1a1a25', '#252530', '#303040']
    if (hour >= 6 && hour < 8) return ['#1a1030', '#4a2060', '#d06040', '#f0a040'] // sunrise
    if (hour >= 8 && hour < 17) {
      if (overcast) return ['#3a3a4a', '#505568', '#6a7080']
      return ['#1a3050', '#2a5080', '#4a80b0'] // clear day
    }
    if (hour >= 17 && hour < 20) return ['#1a1035', '#5a2060', '#d07040', '#f0b050'] // sunset
    return ['#05050f', '#0a0a1a', '#0f1025'] // night
  }

  function generateCity() {
    const buildingColors = ['#12121e', '#151525', '#1a1a2e', '#18182a', '#101020', '#1e1e30']
    buildings = []
    let bx = 0
    while (bx < PW) {
      const bw = 12 + Math.floor(Math.random() * 18)
      const bh = 40 + Math.floor(Math.random() * 100)
      const color = buildingColors[Math.floor(Math.random() * buildingColors.length)]

      // Windows
      const windows = []
      const winSpacingX = 4
      const winSpacingY = 5
      for (let wx = 2; wx < bw - 3; wx += winSpacingX) {
        for (let wy = 4; wy < bh - 4; wy += winSpacingY) {
          windows.push({
            wx, wy,
            on: Math.random() > 0.4,
            flicker: Math.random() * Math.PI * 2,
          })
        }
      }

      buildings.push({ x: bx, w: bw, h: bh, color, windows })
      bx += bw + Math.floor(Math.random() * 3)
    }

    // Streetlamps
    lamps = []
    for (let lx = 20; lx < PW; lx += 50 + Math.floor(Math.random() * 30)) {
      lamps.push({ x: lx })
    }

    // Stars
    stars = []
    for (let i = 0; i < 60; i++) {
      stars.push({
        x: Math.floor(Math.random() * PW),
        y: Math.floor(Math.random() * PH * 0.3),
        phase: Math.random() * Math.PI * 2,
      })
    }
  }

  function initClouds() {
    const count = weatherDesc.includes('cloud') || weatherDesc.includes('overcast') ? 8 : 4
    clouds = []
    for (let i = 0; i < count; i++) {
      clouds.push({
        x: Math.floor(Math.random() * PW * 1.5),
        y: 10 + Math.floor(Math.random() * 40),
        w: 20 + Math.floor(Math.random() * 30),
        speed: 0.08 + Math.random() * 0.15,
      })
    }
  }

  function initCars() {
    const carColors = ['#e74c3c', '#3498db', '#f1c40f', '#2ecc71', '#e67e22', '#9b59b6']
    cars = []
    for (let i = 0; i < 5; i++) {
      const dir = Math.random() > 0.5 ? 1 : -1
      cars.push({
        x: Math.floor(Math.random() * PW),
        y: PH - 12 + (dir > 0 ? 0 : 4), // two lanes
        w: 5 + Math.floor(Math.random() * 3),
        h: 2,
        speed: (0.2 + Math.random() * 0.3) * dir,
        color: carColors[Math.floor(Math.random() * carColors.length)],
      })
    }
  }

  function initPrecipitation() {
    precipitation = []
    if (weatherDesc.includes('rain') || weatherDesc.includes('drizzle') || weatherDesc.includes('thunderstorm')) {
      for (let i = 0; i < 100; i++) {
        precipitation.push({
          x: Math.floor(Math.random() * PW),
          y: Math.floor(Math.random() * PH),
          speed: 3 + Math.random() * 3,
        })
      }
    } else if (weatherDesc.includes('snow')) {
      for (let i = 0; i < 50; i++) {
        precipitation.push({
          x: Math.floor(Math.random() * PW),
          y: Math.floor(Math.random() * PH),
          speed: 0.3 + Math.random() * 0.5,
        })
      }
    }
  }

  function drawFrame(time) {
    if (!pixelCanvas) return
    const pctx = pixelCanvas.getContext('2d')
    if (!pctx) return

    const speedMult = musicPlaying ? 1.4 : 1.0
    const hour = new Date().getHours()
    const showNightStars = hour >= 20 || hour < 6

    // --- Sky ---
    const skyColors = getSkyColors()
    const skyGrad = pctx.createLinearGradient(0, 0, 0, PH * 0.65)
    skyColors.forEach((c, i) => skyGrad.addColorStop(i / (skyColors.length - 1), c))
    pctx.fillStyle = skyGrad
    pctx.fillRect(0, 0, PW, PH)

    // --- Stars (night only) ---
    if (showNightStars) {
      for (const s of stars) {
        const twinkle = Math.sin(time * 1.5 + s.phase) * 0.5 + 0.5
        if (twinkle > 0.3) {
          pctx.fillStyle = `rgba(255, 255, 255, ${twinkle * 0.8})`
          pctx.fillRect(s.x, s.y, 1, 1)
        }
      }
    }

    // --- Clouds ---
    for (const c of clouds) {
      c.x -= c.speed * speedMult
      if (c.x + c.w < 0) c.x = PW + c.w

      const isOvercast = weatherDesc.includes('overcast') || weatherDesc.includes('cloud')
      const cloudColor = isOvercast ? 'rgba(80, 85, 95, 0.6)' : 'rgba(180, 190, 200, 0.3)'
      pctx.fillStyle = cloudColor
      // Pixel cloud: main body + two bumps
      pctx.fillRect(Math.floor(c.x), Math.floor(c.y), c.w, 5)
      pctx.fillRect(Math.floor(c.x + c.w * 0.15), Math.floor(c.y - 3), Math.floor(c.w * 0.4), 3)
      pctx.fillRect(Math.floor(c.x + c.w * 0.45), Math.floor(c.y - 4), Math.floor(c.w * 0.35), 4)
    }

    // --- Buildings ---
    const groundY = PH - 18
    for (const b of buildings) {
      const by = groundY - b.h
      pctx.fillStyle = b.color
      pctx.fillRect(b.x, by, b.w, b.h)

      // Windows
      for (const win of b.windows) {
        // Music makes windows toggle more
        if (musicPlaying && Math.random() < 0.003) win.on = !win.on
        if (!win.on) continue
        const winAlpha = 0.6 + Math.sin(time * 0.5 + win.flicker) * 0.15
        pctx.fillStyle = `rgba(255, 210, 122, ${winAlpha})`
        pctx.fillRect(b.x + win.wx, by + win.wy, 2, 2)
      }

      // Roof detail (antenna or flat top variation)
      if (b.h > 80 && b.w > 15) {
        pctx.fillStyle = b.color
        pctx.fillRect(b.x + Math.floor(b.w / 2), by - 6, 1, 6) // antenna
        pctx.fillStyle = '#ff3030'
        pctx.fillRect(b.x + Math.floor(b.w / 2), by - 7, 1, 1) // red light
      }
    }

    // --- Street ---
    pctx.fillStyle = '#0a0a12'
    pctx.fillRect(0, groundY, PW, PH - groundY)
    // Road line
    pctx.fillStyle = '#1a1a25'
    pctx.fillRect(0, groundY + 2, PW, 1)
    // Dashed center line
    pctx.fillStyle = '#2a2a35'
    for (let dx = 0; dx < PW; dx += 10) {
      pctx.fillRect(dx, PH - 10, 5, 1)
    }

    // --- Streetlamps ---
    for (const lamp of lamps) {
      pctx.fillStyle = '#1a1a25'
      pctx.fillRect(lamp.x, groundY - 18, 1, 18) // pole
      pctx.fillRect(lamp.x - 1, groundY - 18, 3, 1) // top
      // Warm glow
      pctx.fillStyle = 'rgba(255, 200, 100, 0.15)'
      pctx.fillRect(lamp.x - 3, groundY - 17, 7, 2)
      pctx.fillStyle = 'rgba(255, 200, 100, 0.08)'
      pctx.fillRect(lamp.x - 5, groundY - 15, 11, 15)
    }

    // --- Cars ---
    for (const car of cars) {
      car.x += car.speed * speedMult
      if (car.speed > 0 && car.x > PW + 10) car.x = -car.w - 5
      if (car.speed < 0 && car.x < -car.w - 10) car.x = PW + 5

      pctx.fillStyle = car.color
      pctx.fillRect(Math.floor(car.x), car.y, car.w, car.h)
      // Windshield
      pctx.fillStyle = 'rgba(150, 180, 220, 0.5)'
      const windshieldX = car.speed > 0 ? Math.floor(car.x) + car.w - 1 : Math.floor(car.x)
      pctx.fillRect(windshieldX, car.y, 1, car.h)
    }

    // --- Precipitation ---
    const isSnow = weatherDesc.includes('snow')
    for (const p of precipitation) {
      p.y += p.speed * speedMult
      if (isSnow) p.x += Math.sin(time + p.x * 0.1) * 0.3
      if (p.y > PH) { p.y = -2; p.x = Math.floor(Math.random() * PW) }

      if (isSnow) {
        pctx.fillStyle = 'rgba(255, 255, 255, 0.6)'
        pctx.fillRect(Math.floor(p.x), Math.floor(p.y), 1, 1)
      } else {
        pctx.fillStyle = 'rgba(150, 180, 220, 0.3)'
        pctx.fillRect(Math.floor(p.x), Math.floor(p.y), 1, 2)
      }
    }

    // --- Lightning flash ---
    if (weatherDesc.includes('thunderstorm') && Math.random() < 0.003) {
      pctx.fillStyle = 'rgba(255, 255, 240, 0.2)'
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

    generateCity()
    await fetchWeather()
    initClouds()
    initCars()
    initPrecipitation()

    weatherTimer = setInterval(async () => {
      await fetchWeather()
      initClouds()
      initPrecipitation()
    }, 600_000)

    stopLoop = createAnimationLoop(drawFrame)

    const onResize = () => {
      canvas.width = canvas.clientWidth
      canvas.height = canvas.clientHeight
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
