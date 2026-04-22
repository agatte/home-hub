<script>
  import { onMount, onDestroy } from 'svelte'
  import {
    forceSimulation, forceLink, forceManyBody, forceCollide,
    forceRadial, forceX, forceY,
  } from 'd3-force'
  import { constellationWithContext } from '$lib/stores/constellation.js'
  import { modeColorSoft } from '$lib/theme.js'
  import ModeNucleus from './ModeNucleus.svelte'
  import LaneSatellite from './LaneSatellite.svelte'
  import FactorPip from './FactorPip.svelte'
  import ContextBubble from './ContextBubble.svelte'
  import ConstellationEdge from './ConstellationEdge.svelte'
  import ConstellationLegend from './ConstellationLegend.svelte'
  import ConstellationMobile from './ConstellationMobile.svelte'

  // Canvas sizing — bound to the host container.
  let width = 640
  let height = 520

  /** @type {HTMLElement | null} */
  let container = null
  /** @type {ResizeObserver | null} */
  let resizeObserver = null

  // Mobile switch — below this width we render the stacked-rows fallback.
  let isMobile = false
  /** @type {MediaQueryList | null} */
  let mobileMedia = null

  // Simulation state. Nodes/links live outside Svelte reactivity because
  // d3-force mutates them in place; we trigger re-render by copying the
  // array reference to `tickNodes`/`tickLinks` on each tick.
  /** @type {any[]} */
  let simNodes = []
  /** @type {any[]} */
  let simLinks = []
  /** @type {any[]} */
  let tickNodes = []
  /** @type {any[]} */
  let tickLinks = []

  /** @type {any} */
  let sim = null

  // Radii scale with canvas size so bubbles always sit inside a readable
  // band regardless of viewport. R_MAX is capped well inside CONTEXT_RADIUS
  // so stale/low-weight lanes (which drift toward R_MAX) never collide
  // with outer-ring context bubbles.
  $: minDim = Math.min(width, height)
  $: R_MIN = Math.round(minDim * 0.22)
  $: R_MAX = Math.round(minDim * 0.32)
  $: CONTEXT_RADIUS = Math.round(minDim * 0.48)

  /** @param {number | null | undefined} weight */
  function laneDistance(weight) {
    const w = Math.max(0, Math.min(1, weight || 0))
    return R_MIN + (R_MAX - R_MIN) * (1 - Math.pow(w, 0.6))
  }
  /** Distance adjusted for staleness — stale lanes drift further out. */
  function targetDistanceForLane(n) {
    const base = laneDistance(n.weight)
    return n.stale ? base + 35 : base
  }
  // Factor pills sit close to their parent lane — not far enough to crowd
  // neighboring lanes. Heavier impact sits closer to the disc.
  function factorDistance(impact) {
    const i = Math.max(0, Math.min(1, impact || 0))
    return 48 + 22 * (1 - i)
  }

  /** Custom force — pull factor nodes toward their parent lane's position. */
  function forceFactorOrbit(nodesRef) {
    let nodes = nodesRef
    /** @type {Map<string, any>} */
    const parents = new Map()
    function reindex() {
      parents.clear()
      for (const n of nodes) {
        if (n.type === 'lane') parents.set(n.id, n)
      }
    }
    reindex()
    function force(alpha) {
      for (const n of nodes) {
        if (n.type !== 'factor') continue
        const p = parents.get(n.parentId)
        if (!p) continue
        const dx = p.x - n.x
        const dy = p.y - n.y
        const dist = Math.max(1, Math.sqrt(dx * dx + dy * dy))
        const target = factorDistance(n.impact)
        // Cap the alpha floor used by this force so pips keep orbiting even
        // after the simulation has otherwise cooled.
        const a = Math.max(alpha, 0.1)
        const pull = (dist - target) / dist
        n.vx += dx * pull * a * 0.25
        n.vy += dy * pull * a * 0.25
      }
    }
    force.initialize = (n) => {
      nodes = n
      reindex()
    }
    return force
  }

  /** Ambient drift — a slow sinusoidal jitter so the whole constellation
   * keeps breathing even after d3-force has converged. Each node gets its
   * own phase on creation; we modulate velocity by a tiny amount per tick. */
  function forceAmbientDrift(nodesRef) {
    let nodes = nodesRef
    const t0 = performance.now()
    function force(alpha) {
      const t = (performance.now() - t0) / 1000
      // Run independently of d3's cooling alpha so drift stays visible at
      // the constant low alpha we keep the sim at. Internal minimum floor
      // ensures we still move when parent alpha is tiny.
      const a = Math.max(alpha || 0, 0.6)
      for (const n of nodes) {
        if (n.type === 'nucleus') continue
        const phase = n._phase || 0
        const freq = n.type === 'factor' ? 0.6 : 0.3
        const amp = (n.type === 'factor' ? 0.5 : 0.35) * a
        n.vx += Math.cos(t * freq + phase) * amp
        n.vy += Math.sin(t * freq * 0.85 + phase * 1.3) * amp
      }
    }
    force.initialize = (n) => { nodes = n }
    return force
  }

  function center() {
    // Nudge the nucleus slightly above geometric center in landscape
    // frames so the context ring's bottom bubbles don't collide with
    // the FloatingNav sitting below the SVG.
    const cy = width > height * 1.15 ? height * 0.48 : height / 2
    return { cx: width / 2, cy }
  }

  // Evenly space the 6 lanes around the nucleus so the starting layout
  // doesn't all clump into one hemisphere. The simulation will refine from
  // here, but the clock-position is deterministic.
  const LANE_ANGLE = {
    process:     -Math.PI / 2,                         // 12 o'clock
    camera:      -Math.PI / 2 + (1 * Math.PI) / 3,     // 2 o'clock
    audio_ml:    -Math.PI / 2 + (2 * Math.PI) / 3,     // 4 o'clock
    behavioral:  -Math.PI / 2 + (3 * Math.PI) / 3,     // 6 o'clock
    rule_engine: -Math.PI / 2 + (4 * Math.PI) / 3,     // 8 o'clock
    presence:    -Math.PI / 2 + (5 * Math.PI) / 3,     // 10 o'clock
  }

  // Outer context ring — 5 non-voting bubbles at a radius derived from
  // canvas size (see CONTEXT_RADIUS above), offset by 36° (π/5) from the
  // lane angles so context doesn't sit directly over a voter's line of
  // sight to the nucleus.
  const CONTEXT_KEYS = ['time', 'weather', 'presence', 'override', 'sonos']
  const CONTEXT_ANGLE_OFFSET = Math.PI / 5
  /** @param {string} key */
  function contextAngle(key) {
    const i = CONTEXT_KEYS.indexOf(key)
    if (i < 0) return 0
    return -Math.PI / 2 + CONTEXT_ANGLE_OFFSET + (i * 2 * Math.PI) / CONTEXT_KEYS.length
  }

  function buildSimNodes(graph) {
    // Preserve existing x/y from the previous graph so nodes don't jump on
    // every snapshot — only new nodes get a deterministic seed near their target.
    const prev = new Map(simNodes.map((n) => [n.id, n]))
    const { cx, cy } = center()
    // Per-parent factor index so each lane's pips start at distinct angles.
    /** @type {Map<string, number>} */
    const factorIndex = new Map()
    return graph.nodes.map((n) => {
      const old = prev.get(n.id)
      if (old) {
        return Object.assign(old, n)
      }
      let x = cx, y = cy
      if (n.type === 'lane') {
        const angle = LANE_ANGLE[n.lane] ?? Math.random() * Math.PI * 2
        const r = laneDistance(n.weight)
        x = cx + Math.cos(angle) * r
        y = cy + Math.sin(angle) * r
      } else if (n.type === 'factor') {
        const parent = prev.get(n.parentId)
        const parentLaneAngle = LANE_ANGLE[n.lane] ?? 0
        const px = parent ? parent.x : cx + Math.cos(parentLaneAngle) * laneDistance(0.2)
        const py = parent ? parent.y : cy + Math.sin(parentLaneAngle) * laneDistance(0.2)
        // Fan the pips outward — they sit on the far side of the parent from
        // the nucleus, spread in a small arc by index.
        const i = factorIndex.get(n.parentId) || 0
        factorIndex.set(n.parentId, i + 1)
        const baseAngle = parentLaneAngle  // radial direction from center
        const spread = (i - 1) * 0.55  // ~32° fan per pip, centered
        const angle = baseAngle + spread
        const r = factorDistance(n.impact)
        x = px + Math.cos(angle) * r
        y = py + Math.sin(angle) * r
      } else if (n.type === 'context') {
        const angle = contextAngle(n.key)
        x = cx + Math.cos(angle) * CONTEXT_RADIUS
        y = cy + Math.sin(angle) * CONTEXT_RADIUS
      }
      return Object.assign({}, n, {
        x, y, vx: 0, vy: 0,
        // Unique phase per node for the ambient drift force.
        _phase: Math.random() * Math.PI * 2,
      })
    })
  }

  function buildSimLinks(graph, nodesById) {
    return graph.links.map((l) => ({
      source: nodesById.get(l.source),
      target: nodesById.get(l.target),
      weight: l.weight,
      agrees: l.agrees,
      stale: l.stale,
      hasData: l.hasData,
    })).filter((l) => l.source && l.target)
  }

  function rebuildSimulation(graph) {
    const { cx, cy } = center()
    simNodes = buildSimNodes(graph)
    const byId = new Map(simNodes.map((n) => [n.id, n]))
    simLinks = buildSimLinks(graph, byId)

    // Pin the nucleus in the center so the whole system orbits it cleanly.
    for (const n of simNodes) {
      if (n.type === 'nucleus') {
        n.fx = cx
        n.fy = cy
      } else {
        n.fx = null
        n.fy = null
      }
    }

    if (!sim) {
      // Constant low-alpha simulation — alphaDecay(0) means alpha never
      // decays, so d3-force keeps ticking forever at a gentle energy level.
      // That lets the ambient drift force produce visible motion without
      // the "heat up → freeze → heat up" cycle a standard decaying sim has.
      sim = forceSimulation(simNodes)
        .alphaDecay(0)
        .alphaMin(0)
        .alpha(0.1)
        .velocityDecay(0.6)
        .force('charge', forceManyBody().strength((n) => (
          n.type === 'factor' ? -40 :
          n.type === 'context' ? -20 :
          -140
        )))
        .force('collide', forceCollide().radius((n) => (
          n.type === 'nucleus' ? 108 :
          n.type === 'lane' ? 62 :
          n.type === 'context' ? 42 :
          26 + (n.impact || 0.5) * 10
        )).strength(0.95))
        .force('link', forceLink(simLinks).id((n) => n.id).distance((l) => (
          laneDistance(l.weight)
        )).strength((l) => 0.25 + 0.3 * (l.weight || 0)))
        .force('laneRing', forceRadial((n) => (
          n.type === 'lane' ? targetDistanceForLane(n) : 0
        ), cx, cy).strength((n) => n.type === 'lane' ? 0.6 : 0))
        // Outer context ring — pins context bubbles at CONTEXT_RADIUS so
        // they orbit visibly outside the voter constellation.
        .force('contextRing', forceRadial(
          (n) => (n.type === 'context' ? CONTEXT_RADIUS : 0),
          cx, cy,
        ).strength((n) => (n.type === 'context' ? 0.4 : 0)))
        .force('factorOrbit', forceFactorOrbit(simNodes))
        .force('ambient', forceAmbientDrift(simNodes))
        // Mild centering so drifting pips don't escape the canvas.
        .force('x', forceX(cx).strength(0.02))
        .force('y', forceY(cy).strength(0.02))
        .on('tick', () => {
          // Clamp to viewport so stale drifters don't vanish off-screen.
          // Context bubbles carry a larger radius, so give them more room.
          for (const n of simNodes) {
            if (n.type === 'nucleus') continue
            const m = n.type === 'context' ? 44 : n.type === 'lane' ? 58 : 20
            n.x = Math.max(m, Math.min(width - m, n.x))
            n.y = Math.max(m, Math.min(height - m, n.y))
          }
          tickNodes = [...simNodes]
          tickLinks = [...simLinks]
        })

      // alphaDecay(0) + alphaMin(0) means the sim runs forever at alpha=0.1.
      // No heartbeat needed — ambient drift alone supplies the ongoing motion.
    } else {
      sim.nodes(simNodes)
      sim.force('link').links(simLinks)
      sim.force('laneRing', forceRadial((n) => (
        n.type === 'lane' ? targetDistanceForLane(n) : 0
      ), cx, cy).strength((n) => n.type === 'lane' ? 0.6 : 0))
      sim.force('contextRing', forceRadial(
        (n) => (n.type === 'context' ? CONTEXT_RADIUS : 0),
        cx, cy,
      ).strength((n) => (n.type === 'context' ? 0.4 : 0)))
      // Brief kick to let the ring reshuffle after new data lands, then
      // settle back to the constant idle alpha.
      sim.alpha(0.3).restart()
      setTimeout(() => { if (sim) sim.alpha(0.1) }, 600)
    }
  }

  function resize() {
    if (!container) return
    const rect = container.getBoundingClientRect()
    width = Math.max(320, rect.width)
    height = Math.max(420, Math.min(rect.height || 560, width * 0.78))
    if (sim) {
      const { cx, cy } = center()
      for (const n of simNodes) {
        if (n.type === 'nucleus') {
          n.fx = cx
          n.fy = cy
        }
      }
      sim.force('laneRing', forceRadial((n) => (
        n.type === 'lane' ? targetDistanceForLane(n) : 0
      ), cx, cy).strength((n) => n.type === 'lane' ? 0.6 : 0))
      sim.force('contextRing', forceRadial(
        (n) => (n.type === 'context' ? CONTEXT_RADIUS : 0),
        cx, cy,
      ).strength((n) => (n.type === 'context' ? 0.4 : 0)))
      sim.force('x', forceX(cx).strength(0.02))
      sim.force('y', forceY(cy).strength(0.02))
      sim.alpha(0.3).restart()
    }
  }

  onMount(() => {
    if (typeof window !== 'undefined') {
      mobileMedia = window.matchMedia('(max-width: 600px)')
      const handler = (e) => { isMobile = e.matches }
      isMobile = mobileMedia.matches
      mobileMedia.addEventListener('change', handler)

      resizeObserver = new ResizeObserver(() => resize())
      if (container) resizeObserver.observe(container)
      resize()
    }

    const unsub = constellationWithContext.subscribe((graph) => {
      if (!graph || graph.nodes.length === 0) return
      rebuildSimulation(graph)
    })

    return () => {
      unsub()
      if (mobileMedia) mobileMedia.removeEventListener('change', () => {})
      if (resizeObserver) resizeObserver.disconnect()
      if (sim) sim.stop()
      sim = null
    }
  })

  onDestroy(() => {
    if (sim) sim.stop()
    sim = null
  })

  // Reactive derived pieces for the nucleus label
  $: fusedMode = $constellationWithContext.fusedMode || 'idle'
  $: fusedConf = $constellationWithContext.fusedConfidence || 0
</script>

{#if isMobile}
  <ConstellationMobile graph={$constellationWithContext} />
{:else}
  <section class="constellation" bind:this={container}>
    <svg
      class="canvas"
      viewBox="0 0 {width} {height}"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label="Signal constellation"
    >
      <!-- Ambient glow behind the nucleus -->
      <defs>
        <radialGradient id="nucleus-glow">
          <stop offset="0%" stop-color={modeColorSoft(fusedMode, 0.35)} />
          <stop offset="70%" stop-color={modeColorSoft(fusedMode, 0.05)} />
          <stop offset="100%" stop-color="transparent" />
        </radialGradient>
      </defs>

      <circle
        cx={center().cx}
        cy={center().cy}
        r={Math.min(width, height) * 0.36}
        fill="url(#nucleus-glow)"
        class="aura"
      />

      <!-- Context tethers — dim dashed lines anchoring active context
           bubbles back to the nucleus, so they read as "orbit, not drift". -->
      <g class="context-tethers">
        {#each tickNodes.filter((n) => n.type === 'context' && n.active) as node (node.id)}
          <line
            x1={center().cx}
            y1={center().cy}
            x2={node.x}
            y2={node.y}
            class="tether"
          />
        {/each}
      </g>

      <!-- Context ring (outermost, beneath the voter edges) -->
      <g class="context-ring">
        {#each tickNodes.filter((n) => n.type === 'context') as node (node.id)}
          <ContextBubble {node} {fusedMode} />
        {/each}
      </g>

      <!-- Edges (beneath voter nodes) -->
      <g class="edges">
        {#each tickLinks as link (link.source.id + '-' + link.target.id)}
          <ConstellationEdge {link} {fusedMode} />
        {/each}
      </g>

      <!-- Factor pips (beneath lane bubbles so lane sits on top) -->
      <g class="factors">
        {#each tickNodes.filter((n) => n.type === 'factor') as node (node.id)}
          <FactorPip {node} {fusedMode} />
        {/each}
      </g>

      <!-- Lane satellites -->
      <g class="lanes">
        {#each tickNodes.filter((n) => n.type === 'lane') as node (node.id)}
          <LaneSatellite {node} {fusedMode} />
        {/each}
      </g>

      <!-- Nucleus on top -->
      {#each tickNodes.filter((n) => n.type === 'nucleus') as node (node.id)}
        <ModeNucleus {node} confidence={fusedConf} />
      {/each}
    </svg>

    <ConstellationLegend />
  </section>
{/if}

<style>
  .constellation {
    position: relative;
    width: 100%;
    max-width: 980px;
    margin: 0 auto;
    aspect-ratio: 16 / 11;
    min-height: 440px;
    /* Must clear the fixed FloatingNav (56px tall, bottom: 20px) +
       the ModeOverlay header at the top of the page. */
    max-height: 620px;
  }
  .canvas {
    width: 100%;
    height: 100%;
    display: block;
  }
  .tether {
    stroke: rgba(255, 255, 255, 0.12);
    stroke-width: 1;
    stroke-dasharray: 2 6;
    stroke-linecap: round;
    pointer-events: none;
  }
  .aura {
    animation: auraPulse 6s ease-in-out infinite;
    transform-origin: center;
    transform-box: fill-box;
  }
  @keyframes auraPulse {
    0%, 100% { opacity: 0.55; }
    50%      { opacity: 0.9;  }
  }
</style>
