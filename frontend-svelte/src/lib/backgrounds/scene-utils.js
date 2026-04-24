/**
 * Shared drawing utilities for Canvas2D background scenes.
 */

const TARGET_FPS = 15
const FRAME_INTERVAL = 1000 / TARGET_FPS

/**
 * Initialize a canvas with DPR scaling. Returns {ctx, w, h, dpr}.
 * @param {HTMLCanvasElement} canvas
 */
export function initSceneCanvas(canvas) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  const w = canvas.clientWidth
  const h = canvas.clientHeight
  canvas.width = w * dpr
  canvas.height = h * dpr
  const ctx = canvas.getContext('2d')
  ctx.scale(dpr, dpr)
  return { ctx, w, h, dpr }
}

/**
 * Create a 15fps animation loop. Returns a stop function.
 *
 * Honours prefers-reduced-motion: when set, the loop renders one frame so the
 * scene isn't a black rectangle, then stops. Pure-CSS gates can't do that for
 * canvas-based scenes — they just freeze whatever was last drawn.
 * @param {(time: number, dt: number) => void} onFrame
 */
export function createAnimationLoop(onFrame) {
  let animId = 0
  let lastFrame = 0
  let time = 0

  // matchMedia is unavailable during SSR — guard the access.
  const reduceMotion =
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches

  if (reduceMotion) {
    // One static frame so the scene shows something, then stop.
    requestAnimationFrame((ts) => onFrame(ts * 0.001, 0))
    return () => {}
  }

  function tick(ts) {
    animId = requestAnimationFrame(tick)
    const elapsed = ts - lastFrame
    if (elapsed < FRAME_INTERVAL) return
    lastFrame = ts - (elapsed % FRAME_INTERVAL)
    time += elapsed * 0.001
    onFrame(time, elapsed * 0.001)
  }

  animId = requestAnimationFrame(tick)
  return () => cancelAnimationFrame(animId)
}

/**
 * Parse hex color to {r, g, b}.
 * @param {string} hex
 */
export function hexToRGB(hex) {
  const n = parseInt(hex.slice(1), 16)
  return { r: (n >> 16) & 0xff, g: (n >> 8) & 0xff, b: n & 0xff }
}

/**
 * Draw twinkling pixel stars on a dark sky.
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} w
 * @param {number} h
 * @param {number} time
 * @param {Array<{x:number,y:number,phase:number,size:number}>} stars
 */
export function drawStars(ctx, w, h, time, stars) {
  for (const s of stars) {
    const twinkle = Math.sin(time * 2 + s.phase) * 0.5 + 0.5
    const alpha = 0.3 + twinkle * 0.7
    ctx.fillStyle = `rgba(255, 255, 255, ${alpha})`
    ctx.fillRect(Math.floor(s.x), Math.floor(s.y), s.size, s.size)
  }
}

/**
 * Create an array of star objects.
 * @param {number} count
 * @param {number} w
 * @param {number} maxY - max Y position (stars only in upper portion)
 */
export function createStars(count, w, maxY) {
  const stars = []
  for (let i = 0; i < count; i++) {
    stars.push({
      x: Math.random() * w,
      y: Math.random() * maxY,
      phase: Math.random() * Math.PI * 2,
      size: Math.random() > 0.85 ? 2 : 1,
    })
  }
  return stars
}

/**
 * Rain drop system — creates and animates raindrops.
 */
export function createRainDrops(count, w, h) {
  const drops = []
  for (let i = 0; i < count; i++) {
    drops.push({
      x: Math.random() * w,
      y: Math.random() * h,
      speed: 3 + Math.random() * 4,
      length: 8 + Math.random() * 15,
      opacity: 0.1 + Math.random() * 0.2,
    })
  }
  return drops
}

/**
 * Update and draw rain drops.
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} w
 * @param {number} h
 * @param {Array} drops
 * @param {number} speedMult
 * @param {string} [color='#60a5fa']
 */
export function drawRain(ctx, w, h, drops, speedMult = 1, color = '#60a5fa') {
  const c = hexToRGB(color)
  for (const d of drops) {
    d.y += d.speed * speedMult
    d.x -= d.speed * 0.15 // slight wind angle

    if (d.y > h) {
      d.y = -d.length
      d.x = Math.random() * (w + 50)
    }

    ctx.strokeStyle = `rgba(${c.r}, ${c.g}, ${c.b}, ${d.opacity})`
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(d.x, d.y)
    ctx.lineTo(d.x - d.speed * 0.15 * (d.length / d.speed), d.y - d.length)
    ctx.stroke()
  }
}

/**
 * Snow flake system.
 */
export function createSnowFlakes(count, w, h) {
  const flakes = []
  for (let i = 0; i < count; i++) {
    flakes.push({
      x: Math.random() * w,
      y: Math.random() * h,
      speed: 0.5 + Math.random() * 1.5,
      size: 1 + Math.random() * 3,
      drift: Math.random() * Math.PI * 2,
      opacity: 0.3 + Math.random() * 0.5,
    })
  }
  return flakes
}

/**
 * Update and draw snow flakes.
 */
export function drawSnow(ctx, w, h, flakes, time) {
  for (const f of flakes) {
    f.y += f.speed
    f.x += Math.sin(time + f.drift) * 0.5

    if (f.y > h) {
      f.y = -f.size
      f.x = Math.random() * w
    }

    ctx.fillStyle = `rgba(255, 255, 255, ${f.opacity})`
    ctx.beginPath()
    ctx.arc(f.x, f.y, f.size, 0, Math.PI * 2)
    ctx.fill()
  }
}
