<script>
  import { onMount, onDestroy } from 'svelte'
  import {
    forceSimulation, forceLink, forceManyBody, forceCollide,
    forceRadial, forceX, forceY,
  } from 'd3-force'
  import { constellation } from '$lib/stores/constellation.js'
  import { modeColor, modeColorSoft, modeLabel } from '$lib/theme.js'
  import ModeNucleus from './ModeNucleus.svelte'
  import LaneSatellite from './LaneSatellite.svelte'
  import FactorPip from './FactorPip.svelte'
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

  // Radial distance mapping. Lanes sit at 95..220px from center, heavier
  // weights closer to the nucleus. See plan §3 for the curve.
  const R_MIN = 95
  const R_MAX = 220
  /** @param {number | null | undefined} weight */
  function laneDistance(weight) {
    const w = Math.max(0, Math.min(1, weight || 0))
    return R_MIN + (R_MAX - R_MIN) * (1 - Math.pow(w, 0.6))
  }
  /** Distance adjusted for staleness — stale lanes drift further out. */
  function targetDistanceForLane(n) {
    const base = laneDistance(n.weight)
    return n.stale ? base + 40 : base
  }
  // Factor pips sit 38..68px from their parent lane, heavier impact closer.
  function factorDistance(impact) {
    const i = Math.max(0, Math.min(1, impact || 0))
    return 38 + 30 * (1 - i)
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
        const pull = (dist - target) / dist
        // Softer strength so pips orbit loosely; alpha scales down over time.
        n.vx += dx * pull * alpha * 0.35
        n.vy += dy * pull * alpha * 0.35
      }
    }
    force.initialize = (n) => {
      nodes = n
      reindex()
    }
    return force
  }

  function center() {
    return { cx: width / 2, cy: height / 2 }
  }

  function buildSimNodes(graph) {
    // Preserve existing x/y from the previous graph so nodes don't jump on
    // every snapshot — only new nodes get a random seed near their target.
    const prev = new Map(simNodes.map((n) => [n.id, n]))
    const { cx, cy } = center()
    return graph.nodes.map((n) => {
      const old = prev.get(n.id)
      if (old) {
        return Object.assign(old, n)
      }
      // Seed new nodes at a rough starting position so they don't all spawn
      // on top of each other and fly outward at t=0.
      let x = cx, y = cy
      if (n.type === 'lane') {
        const angle = Math.random() * Math.PI * 2
        const r = laneDistance(n.weight)
        x = cx + Math.cos(angle) * r
        y = cy + Math.sin(angle) * r
      } else if (n.type === 'factor') {
        // Place near parent if we can find it in the previous graph
        const parent = prev.get(n.parentId)
        const px = parent ? parent.x : cx
        const py = parent ? parent.y : cy
        const angle = Math.random() * Math.PI * 2
        const r = factorDistance(n.impact)
        x = px + Math.cos(angle) * r
        y = py + Math.sin(angle) * r
      }
      return Object.assign({}, n, { x, y, vx: 0, vy: 0 })
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
      sim = forceSimulation(simNodes)
        .alphaDecay(0.035)
        .velocityDecay(0.45)
        .force('charge', forceManyBody().strength((n) => n.type === 'factor' ? -25 : -70))
        .force('collide', forceCollide().radius((n) => (
          n.type === 'nucleus' ? 80 :
          n.type === 'lane' ? 38 :
          20 + n.impact * 8
        )))
        .force('link', forceLink(simLinks).id((n) => n.id).distance((l) => (
          laneDistance(l.weight)
        )).strength((l) => 0.35 + 0.4 * (l.weight || 0)))
        .force('laneRing', forceRadial((n) => (
          n.type === 'lane' ? laneDistance(n.weight) : 0
        ), cx, cy).strength((n) => n.type === 'lane' ? 0.5 : 0))
        .force('factorOrbit', forceFactorOrbit(simNodes))
        // Mild centering so drifting pips don't escape the canvas.
        .force('x', forceX(cx).strength(0.02))
        .force('y', forceY(cy).strength(0.02))
        .on('tick', () => {
          // Clamp to viewport so stale drifters don't vanish off-screen.
          const margin = 24
          for (const n of simNodes) {
            if (n.type === 'nucleus') continue
            n.x = Math.max(margin, Math.min(width - margin, n.x))
            n.y = Math.max(margin, Math.min(height - margin, n.y))
          }
          tickNodes = [...simNodes]
          tickLinks = [...simLinks]
        })
    } else {
      sim.nodes(simNodes)
      sim.force('link').links(simLinks)
      sim.force('laneRing', forceRadial((n) => (
        n.type === 'lane' ? targetDistanceForLane(n) : 0
      ), cx, cy).strength((n) => n.type === 'lane' ? 0.5 : 0))
      sim.alpha(0.5).restart()
    }
  }

  function resize() {
    if (!container) return
    const rect = container.getBoundingClientRect()
    width = Math.max(320, rect.width)
    height = Math.max(380, Math.min(rect.height || 520, width * 0.8))
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
      ), cx, cy).strength((n) => n.type === 'lane' ? 0.5 : 0))
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

    const unsub = constellation.subscribe((graph) => {
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
  $: fusedMode = $constellation.fusedMode || 'idle'
  $: fusedConf = $constellation.fusedConfidence || 0
</script>

{#if isMobile}
  <ConstellationMobile graph={$constellation} />
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
        cx={width / 2}
        cy={height / 2}
        r={Math.min(width, height) * 0.38}
        fill="url(#nucleus-glow)"
        class="aura"
      />

      <!-- Edges (beneath nodes) -->
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

    <ConstellationLegend
      mode={fusedMode}
      modeLabelText={modeLabel(fusedMode)}
      confidence={fusedConf}
    />
  </section>
{/if}

<style>
  .constellation {
    position: relative;
    width: 100%;
    max-width: 900px;
    margin: 0 auto;
    aspect-ratio: 5 / 4;
    min-height: 380px;
    max-height: 640px;
  }
  .canvas {
    width: 100%;
    height: 100%;
    display: block;
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
