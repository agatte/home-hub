<script>
  import { onMount, onDestroy } from 'svelte'
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

  const unsub = sonos.subscribe(($s) => { musicPlaying = $s.state === 'PLAYING' })

  // Stars
  /** @type {Array<{x:number,y:number,phase:number,size:number}>} */
  let stars = []

  // Aurora curtain definitions
  const CURTAINS = [
    { baseX: 0.2, speed: 0.12, freq: 0.008, amp: 80, width: 0.25, hue: 140, satStart: 70, satEnd: 50 },
    { baseX: 0.45, speed: 0.08, freq: 0.006, amp: 100, width: 0.3, hue: 160, satStart: 65, satEnd: 45 },
    { baseX: 0.7, speed: 0.15, freq: 0.01, amp: 60, width: 0.2, hue: 120, satStart: 60, satEnd: 55 },
    { baseX: 0.35, speed: 0.06, freq: 0.005, amp: 120, width: 0.35, hue: 270, satStart: 50, satEnd: 35 },
  ]

  // Treeline heights (generated once)
  /** @type {number[]} */
  let treeline = []

  function generateTreeline() {
    treeline = []
    const baseY = h * 0.85
    for (let x = 0; x <= w; x += 2) {
      // Mix of slow hills and spiky trees
      const hill = Math.sin(x * 0.003) * 20 + Math.sin(x * 0.008) * 10
      const tree = Math.abs(Math.sin(x * 0.05)) * 15 * (Math.sin(x * 0.02) * 0.5 + 0.5)
      treeline.push(baseY - hill - tree)
    }
  }

  function drawFrame(time) {
    if (!ctx) return

    const speedMult = musicPlaying ? 1.5 : 1.0
    const brightMult = musicPlaying ? 1.3 : 1.0

    // --- Night sky gradient ---
    const skyGrad = ctx.createLinearGradient(0, 0, 0, h)
    skyGrad.addColorStop(0, '#030308')
    skyGrad.addColorStop(0.4, '#050510')
    skyGrad.addColorStop(0.7, '#0a0a1a')
    skyGrad.addColorStop(1, '#0a0a15')
    ctx.fillStyle = skyGrad
    ctx.fillRect(0, 0, w, h)

    // --- Stars ---
    for (const s of stars) {
      const twinkle = Math.sin(time * 1.8 + s.phase) * 0.5 + 0.5
      const alpha = (0.2 + twinkle * 0.6) * (musicPlaying ? 1.1 : 1)
      ctx.fillStyle = `rgba(255, 255, 255, ${alpha})`
      ctx.beginPath()
      ctx.arc(s.x, s.y, s.size * 0.8, 0, Math.PI * 2)
      ctx.fill()
    }

    // --- Aurora curtains ---
    for (const curtain of CURTAINS) {
      const curtainTop = h * 0.08
      const curtainBot = h * 0.6
      const curtainHeight = curtainBot - curtainTop

      for (let y = curtainTop; y < curtainBot; y += 2) {
        const progress = (y - curtainTop) / curtainHeight // 0 at top, 1 at bottom

        // Bell curve opacity — brightest at 30-40% from top
        const bellCenter = 0.35
        const bellWidth = 0.35
        const bell = Math.exp(-((progress - bellCenter) ** 2) / (2 * bellWidth ** 2))

        // Undulating x offset
        const xOffset = Math.sin(
          y * curtain.freq + time * curtain.speed * speedMult + curtain.baseX * 10
        ) * curtain.amp * (musicPlaying ? 1.2 : 1)

        const centerX = w * curtain.baseX + xOffset
        const bandWidth = w * curtain.width * (0.3 + bell * 0.7)

        // Color shifts along height: green at top → cyan at middle → purple hint at bottom
        const hueShift = curtain.hue + progress * 30
        const sat = curtain.satStart + (curtain.satEnd - curtain.satStart) * progress
        const light = 40 + bell * 20
        const alpha = bell * 0.12 * brightMult

        if (alpha < 0.005) continue

        const grad = ctx.createLinearGradient(centerX - bandWidth / 2, y, centerX + bandWidth / 2, y)
        grad.addColorStop(0, `hsla(${hueShift}, ${sat}%, ${light}%, 0)`)
        grad.addColorStop(0.3, `hsla(${hueShift}, ${sat}%, ${light}%, ${alpha * 0.6})`)
        grad.addColorStop(0.5, `hsla(${hueShift}, ${sat}%, ${light}%, ${alpha})`)
        grad.addColorStop(0.7, `hsla(${hueShift}, ${sat}%, ${light}%, ${alpha * 0.6})`)
        grad.addColorStop(1, `hsla(${hueShift}, ${sat}%, ${light}%, 0)`)

        ctx.fillStyle = grad
        ctx.fillRect(centerX - bandWidth / 2, y, bandWidth, 3)
      }
    }

    // --- Treeline silhouette ---
    ctx.fillStyle = '#0a0a12'
    ctx.beginPath()
    ctx.moveTo(0, h)
    for (let i = 0; i < treeline.length; i++) {
      ctx.lineTo(i * 2, treeline[i])
    }
    ctx.lineTo(w, h)
    ctx.closePath()
    ctx.fill()

    // --- Aurora reflection on "lake" below treeline ---
    const lakeTop = h * 0.87
    if (lakeTop < h) {
      ctx.save()
      ctx.globalAlpha = 0.04 * brightMult
      ctx.beginPath()
      ctx.rect(0, lakeTop, w, h - lakeTop)
      ctx.clip()

      // Simplified reflection — just draw faint horizontal streaks in aurora colors
      for (const curtain of CURTAINS) {
        const hue = curtain.hue
        for (let ry = lakeTop; ry < h; ry += 4) {
          const ripple = Math.sin(ry * 0.05 + time * 0.3) * 30
          const cx = w * curtain.baseX + ripple
          const rw = w * curtain.width * 0.4
          const alpha = (1 - (ry - lakeTop) / (h - lakeTop)) * 0.8

          ctx.fillStyle = `hsla(${hue}, 50%, 40%, ${alpha})`
          ctx.fillRect(cx - rw / 2, ry, rw, 2)
        }
      }

      ctx.restore()
    }

    // --- Subtle ground glow from aurora ---
    const glowGrad = ctx.createLinearGradient(0, h * 0.75, 0, h)
    glowGrad.addColorStop(0, 'rgba(34, 197, 94, 0.02)')
    glowGrad.addColorStop(1, 'rgba(34, 197, 94, 0)')
    ctx.fillStyle = glowGrad
    ctx.fillRect(0, h * 0.75, w, h * 0.25)
  }

  function handleResize() {
    const info = initSceneCanvas(canvas)
    ctx = info.ctx
    w = info.w
    h = info.h
    stars = createStars(100, w, h * 0.5)
    generateTreeline()
  }

  onMount(() => {
    const info = initSceneCanvas(canvas)
    ctx = info.ctx
    w = info.w
    h = info.h
    stars = createStars(100, w, h * 0.5)
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
