<script>
  import { onMount, onDestroy } from 'svelte'
  import { sonos } from '$lib/stores/sonos.js'
  import { initSceneCanvas, createAnimationLoop } from './scene-utils.js'

  /** @type {HTMLCanvasElement} */
  let canvas
  /** @type {HTMLCanvasElement} */
  let pixelCanvas // off-screen low-res canvas
  let stopLoop = () => {}
  let musicPlaying = false

  const unsub = sonos.subscribe(($s) => { musicPlaying = $s.state === 'PLAYING' })

  // Pixel art resolution (scaled 4× to 1920×1080)
  const PW = 480
  const PH = 270

  // --- Terrain layers (generated once) ---
  /** @type {number[]} */
  let mountainHeight = []
  /** @type {number[]} */
  let hillHeight = []
  /** @type {number[]} */
  let groundHeight = []

  // --- Stars ---
  /** @type {Array<{x:number,y:number,phase:number}>} */
  let stars = []

  // --- Sprites (walking characters) ---
  const SPRITE_FRAMES = [
    // Frame 0: standing
    [
      [0,0,1,1,0,0],
      [0,1,1,1,1,0],
      [0,0,1,1,0,0],
      [0,1,1,1,1,0],
      [0,1,0,0,1,0],
      [0,0,1,0,0,1],
      [0,1,0,0,1,0],
      [0,0,0,0,0,0],
    ],
    // Frame 1: walk left
    [
      [0,0,1,1,0,0],
      [0,1,1,1,1,0],
      [0,0,1,1,0,0],
      [0,1,1,1,1,0],
      [0,0,1,1,0,0],
      [0,1,0,0,0,0],
      [1,0,0,0,1,0],
      [0,0,0,0,0,0],
    ],
    // Frame 2: walk right
    [
      [0,0,1,1,0,0],
      [0,1,1,1,1,0],
      [0,0,1,1,0,0],
      [0,1,1,1,1,0],
      [0,0,1,1,0,0],
      [0,0,0,0,1,0],
      [0,1,0,0,0,1],
      [0,0,0,0,0,0],
    ],
  ]

  /** @type {Array<{x:number,y:number,speed:number,frame:number,color:string,frameTimer:number}>} */
  let sprites = []

  // --- Floating pixels ---
  /** @type {Array<{x:number,y:number,vy:number,life:number,color:string}>} */
  let floaters = []

  // --- Shooting star ---
  let shootingStar = { active: false, x: 0, y: 0, vx: 0, vy: 0, life: 0 }

  function generateTerrain() {
    mountainHeight = []
    hillHeight = []
    groundHeight = []
    for (let x = 0; x < PW; x++) {
      // Mountains (back) — tall, slow frequency
      mountainHeight.push(PH * 0.35 + Math.sin(x * 0.008) * 30 + Math.sin(x * 0.02) * 15)
      // Hills (mid) — medium
      hillHeight.push(PH * 0.55 + Math.sin(x * 0.015 + 2) * 20 + Math.sin(x * 0.04) * 10)
      // Ground (front) — flat-ish with minor bumps
      groundHeight.push(PH * 0.78 + Math.sin(x * 0.03 + 5) * 5)
    }
  }

  function generateStars() {
    stars = []
    for (let i = 0; i < 80; i++) {
      stars.push({
        x: Math.floor(Math.random() * PW),
        y: Math.floor(Math.random() * PH * 0.35),
        phase: Math.random() * Math.PI * 2,
      })
    }
  }

  function generateSprites() {
    const colors = ['#c084fc', '#a855f7', '#e879f9']
    sprites = []
    for (let i = 0; i < 3; i++) {
      sprites.push({
        x: Math.floor(Math.random() * PW),
        y: 0, // set in draw based on ground height
        speed: 0.3 + Math.random() * 0.4,
        frame: 0,
        color: colors[i % colors.length],
        frameTimer: 0,
      })
    }
  }

  function initFloaters() {
    floaters = []
    for (let i = 0; i < 15; i++) {
      spawnFloater()
    }
  }

  function spawnFloater() {
    const colors = ['#a855f7', '#c084fc', '#e9d5ff', '#7c3aed']
    floaters.push({
      x: Math.floor(Math.random() * PW),
      y: PH * 0.5 + Math.random() * PH * 0.3,
      vy: -(0.1 + Math.random() * 0.3),
      life: 100 + Math.random() * 200,
      color: colors[Math.floor(Math.random() * colors.length)],
    })
  }

  function drawFrame(time) {
    if (!pixelCanvas) return
    const pctx = pixelCanvas.getContext('2d')
    if (!pctx) return

    const speedMult = musicPlaying ? 1.4 : 1.0

    // --- Sky gradient ---
    const skyGrad = pctx.createLinearGradient(0, 0, 0, PH * 0.6)
    skyGrad.addColorStop(0, '#0a0418')
    skyGrad.addColorStop(0.5, '#1a0a2e')
    skyGrad.addColorStop(1, '#2d1b69')
    pctx.fillStyle = skyGrad
    pctx.fillRect(0, 0, PW, PH)

    // --- Stars ---
    for (const s of stars) {
      const twinkle = Math.sin(time * 1.5 + s.phase) * 0.5 + 0.5
      if (twinkle > 0.3) {
        const alpha = twinkle
        pctx.fillStyle = `rgba(255, 255, 255, ${alpha})`
        pctx.fillRect(s.x, s.y, 1, 1)
      }
    }

    // --- Shooting star ---
    if (!shootingStar.active && Math.random() < 0.002) {
      shootingStar = {
        active: true,
        x: Math.random() * PW * 0.8,
        y: Math.random() * PH * 0.2,
        vx: 3 + Math.random() * 2,
        vy: 1 + Math.random(),
        life: 20 + Math.random() * 15,
      }
    }
    if (shootingStar.active) {
      shootingStar.x += shootingStar.vx
      shootingStar.y += shootingStar.vy
      shootingStar.life -= 1
      const a = shootingStar.life / 35
      pctx.fillStyle = `rgba(255, 255, 255, ${a})`
      pctx.fillRect(Math.floor(shootingStar.x), Math.floor(shootingStar.y), 2, 1)
      pctx.fillStyle = `rgba(200, 180, 255, ${a * 0.5})`
      pctx.fillRect(Math.floor(shootingStar.x - shootingStar.vx), Math.floor(shootingStar.y - shootingStar.vy), 1, 1)
      if (shootingStar.life <= 0) shootingStar.active = false
    }

    // --- Mountains (back layer) ---
    pctx.fillStyle = '#0f0820'
    for (let x = 0; x < PW; x++) {
      pctx.fillRect(x, Math.floor(mountainHeight[x]), 1, PH - Math.floor(mountainHeight[x]))
    }

    // --- Hills (mid layer) ---
    pctx.fillStyle = '#0d0618'
    for (let x = 0; x < PW; x++) {
      pctx.fillRect(x, Math.floor(hillHeight[x]), 1, PH - Math.floor(hillHeight[x]))
    }

    // --- Ground (front layer) ---
    pctx.fillStyle = '#0a0412'
    for (let x = 0; x < PW; x++) {
      pctx.fillRect(x, Math.floor(groundHeight[x]), 1, PH - Math.floor(groundHeight[x]))
    }

    // --- Ground highlight line ---
    pctx.fillStyle = '#1a0a30'
    for (let x = 0; x < PW; x++) {
      pctx.fillRect(x, Math.floor(groundHeight[x]), 1, 1)
    }

    // --- Floating pixels ---
    for (let i = floaters.length - 1; i >= 0; i--) {
      const f = floaters[i]
      f.y += f.vy * speedMult
      f.x += Math.sin(time * 0.5 + f.x * 0.1) * 0.2
      f.life -= 1
      if (f.life <= 0 || f.y < 0) {
        floaters.splice(i, 1)
        continue
      }
      const fadeAlpha = Math.min(1, f.life / 30)
      pctx.globalAlpha = fadeAlpha * 0.8
      pctx.fillStyle = f.color
      pctx.fillRect(Math.floor(f.x), Math.floor(f.y), 1, 1)
      pctx.globalAlpha = 1
    }
    // Spawn new floaters
    const spawnRate = musicPlaying ? 0.15 : 0.06
    if (Math.random() < spawnRate) spawnFloater()

    // --- Sprites ---
    for (const sp of sprites) {
      sp.x += sp.speed * speedMult
      if (sp.x > PW + 10) sp.x = -10
      sp.frameTimer += speedMult
      if (sp.frameTimer > 8) {
        sp.frameTimer = 0
        sp.frame = sp.frame === 1 ? 2 : 1
      }
      // Y position follows ground
      const gx = Math.max(0, Math.min(PW - 1, Math.floor(sp.x)))
      sp.y = Math.floor(groundHeight[gx]) - 8

      const frame = SPRITE_FRAMES[sp.frame]
      for (let py = 0; py < frame.length; py++) {
        for (let px = 0; px < frame[py].length; px++) {
          if (frame[py][px]) {
            pctx.fillStyle = sp.color
            pctx.fillRect(Math.floor(sp.x) + px, sp.y + py, 1, 1)
          }
        }
      }
    }

    // --- Scale to main canvas ---
    if (!canvas) return
    const mainCtx = canvas.getContext('2d')
    if (!mainCtx) return
    mainCtx.imageSmoothingEnabled = false
    mainCtx.drawImage(pixelCanvas, 0, 0, canvas.width, canvas.height)
  }

  onMount(() => {
    // Main canvas at full resolution
    canvas.width = canvas.clientWidth
    canvas.height = canvas.clientHeight

    // Off-screen pixel canvas at low resolution
    pixelCanvas = document.createElement('canvas')
    pixelCanvas.width = PW
    pixelCanvas.height = PH

    generateTerrain()
    generateStars()
    generateSprites()
    initFloaters()

    stopLoop = createAnimationLoop(drawFrame)

    const onResize = () => {
      canvas.width = canvas.clientWidth
      canvas.height = canvas.clientHeight
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
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
