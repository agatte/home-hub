<script>
  import { T, useTask } from '@threlte/core'
  import * as THREE from 'three'

  // Moon orbit timing — full sweep across the sky over ~12 minutes.
  // Tweak via MOON_PERIOD_SECONDS if you want it faster for the spike review.
  const MOON_PERIOD_SECONDS = 720
  const MOON_RADIUS = 14
  const MOON_HEIGHT = 5

  // Sky gradient sphere — uses BackSide so the camera sits inside it.
  // Vertex shader passes world-y to the fragment shader for a vertical gradient.
  const skyVertex = `
    varying float vY;
    void main() {
      vY = position.y;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `
  const skyFragment = `
    varying float vY;
    void main() {
      // Map y from [-30, 30] -> [0, 1]
      float t = clamp((vY + 30.0) / 60.0, 0.0, 1.0);
      // Deep navy at the bottom, near-black at the top, with a faint
      // purple haze on the horizon.
      vec3 horizon = vec3(0.10, 0.08, 0.18);
      vec3 zenith  = vec3(0.01, 0.01, 0.04);
      vec3 col = mix(horizon, zenith, smoothstep(0.0, 1.0, t));
      gl_FragColor = vec4(col, 1.0);
    }
  `
  const skyMaterial = new THREE.ShaderMaterial({
    vertexShader: skyVertex,
    fragmentShader: skyFragment,
    side: THREE.BackSide,
    depthWrite: false,
  })

  // Star field — sparse Points with random positions on a hemisphere.
  function makeStarGeometry(count = 400) {
    const positions = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      // Hemisphere above the horizon, biased toward the zenith.
      const u = Math.random()
      const v = Math.random() * 0.85 + 0.05 // keep above horizon
      const theta = u * Math.PI * 2
      const phi = Math.acos(1 - 2 * v)
      const r = 28
      positions[i * 3 + 0] = r * Math.sin(phi) * Math.cos(theta)
      positions[i * 3 + 1] = Math.abs(r * Math.cos(phi)) + 1
      positions[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta)
    }
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    return geo
  }
  const starGeometry = makeStarGeometry()
  const starMaterial = new THREE.PointsMaterial({
    color: 0xffffff,
    size: 0.12,
    sizeAttenuation: true,
    transparent: true,
    opacity: 0.85,
  })

  // Low-poly city silhouette — generate a row of buildings as extruded
  // boxes with random heights. Stored as a fixed array so the same buildings
  // render every frame (no flicker between Svelte updates).
  function makeBuildings() {
    const buildings = []
    const BUILDING_COUNT = 22
    const SPAN = 30 // total horizontal span
    const startX = -SPAN / 2
    const step = SPAN / BUILDING_COUNT
    for (let i = 0; i < BUILDING_COUNT; i++) {
      const w = step * (0.7 + Math.random() * 0.4)
      const h = 1.5 + Math.random() * 4.5
      const d = 1.5 + Math.random() * 1.2
      const x = startX + i * step + step / 2
      // Sprinkle a few "window" lights — pre-baked positions so the flicker
      // pattern is deterministic per building.
      const windows = []
      const cols = Math.max(1, Math.floor(w * 3))
      const rows = Math.max(1, Math.floor(h * 1.2))
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          if (Math.random() < 0.18) {
            windows.push({
              wx: (c + 0.5) / cols - 0.5,
              wy: (r + 0.5) / rows - 0.5,
              phase: Math.random() * Math.PI * 2,
              speed: 0.4 + Math.random() * 0.8,
            })
          }
        }
      }
      buildings.push({ x, w, h, d, windows })
    }
    return buildings
  }
  const buildings = makeBuildings()

  // Animation state — moon angle + window flicker time.
  let moonX = 0
  let moonY = MOON_HEIGHT
  let moonZ = -MOON_RADIUS
  let windowGroups = [] // Three.Group refs for each building (for flicker)
  let elapsed = 0

  // Honour prefers-reduced-motion — captured once at module-eval time. If
  // set, useTask still fires (Threlte controls the rAF) but we skip the
  // per-frame math so the moon and city silhouette stay still.
  const reduceMotion =
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

  useTask((delta) => {
    if (reduceMotion) return
    elapsed += delta
    // Moon arc: parametric across the sky from east to west.
    // Phase 0 = horizon left, 0.5 = zenith, 1 = horizon right.
    const phase = (elapsed % MOON_PERIOD_SECONDS) / MOON_PERIOD_SECONDS
    const angle = phase * Math.PI // 0 -> PI sweeps left to right
    moonX = -Math.cos(angle) * MOON_RADIUS
    moonY = Math.sin(angle) * 8 + MOON_HEIGHT
    moonZ = -MOON_RADIUS * 0.6

    // Window flicker — modulate intensity per window via group child opacity.
    for (let b = 0; b < windowGroups.length; b++) {
      const group = windowGroups[b]
      if (!group) continue
      const wins = buildings[b].windows
      for (let w = 0; w < wins.length; w++) {
        const child = group.children[w]
        if (!child || !child.material) continue
        const win = wins[w]
        // Slow sinusoidal blink + occasional dim. Stays warm yellow.
        const v = 0.5 + 0.5 * Math.sin(elapsed * win.speed + win.phase)
        const dim = (Math.sin(elapsed * 0.13 + win.phase * 2) + 1) * 0.5
        child.material.opacity = 0.4 + v * 0.5 * (0.6 + dim * 0.4)
      }
    }
  })
</script>

<!-- Camera — slightly above ground, looking toward the city silhouette -->
<T.PerspectiveCamera
  makeDefault
  position={[0, 3, 12]}
  fov={55}
  near={0.1}
  far={200}
>
  <T.Object3D position={[0, 2, 0]} />
</T.PerspectiveCamera>

<!-- Sky dome -->
<T.Mesh material={skyMaterial}>
  <T.SphereGeometry args={[60, 32, 16]} />
</T.Mesh>

<!-- Stars -->
<T.Points geometry={starGeometry} material={starMaterial} />

<!-- Ambient + a subtle moon-tinted directional light -->
<T.AmbientLight intensity={0.18} color={0x8090c0} />
<T.DirectionalLight
  position={[moonX, moonY + 4, moonZ + 2]}
  intensity={0.6}
  color={0xb8c6ff}
/>

<!-- Moon — emissive sphere with a soft halo via a second larger transparent sphere -->
<T.Group position={[moonX, moonY, moonZ]}>
  <T.Mesh>
    <T.SphereGeometry args={[1.0, 32, 32]} />
    <T.MeshStandardMaterial
      color={0xf4f1e8}
      emissive={0xe8e2c4}
      emissiveIntensity={1.4}
      roughness={0.9}
    />
  </T.Mesh>
  <!-- Halo -->
  <T.Mesh>
    <T.SphereGeometry args={[1.6, 32, 32]} />
    <T.MeshBasicMaterial
      color={0xfff4d8}
      transparent
      opacity={0.12}
      depthWrite={false}
    />
  </T.Mesh>
  <T.Mesh>
    <T.SphereGeometry args={[2.4, 32, 32]} />
    <T.MeshBasicMaterial
      color={0xfff4d8}
      transparent
      opacity={0.05}
      depthWrite={false}
    />
  </T.Mesh>
</T.Group>

<!-- City silhouette — buildings + window lights -->
{#each buildings as b, i}
  <T.Group position={[b.x, b.h / 2 - 1, -2]}>
    <!-- Building body -->
    <T.Mesh>
      <T.BoxGeometry args={[b.w, b.h, b.d]} />
      <T.MeshStandardMaterial
        color={0x05070d}
        roughness={1.0}
        metalness={0.0}
      />
    </T.Mesh>
    <!-- Windows — small emissive planes parented to a group we capture for flicker -->
    <T.Group bind:ref={windowGroups[i]} position={[0, 0, b.d / 2 + 0.01]}>
      {#each b.windows as win}
        <T.Mesh position={[win.wx * b.w * 0.8, win.wy * b.h * 0.9, 0]}>
          <T.PlaneGeometry args={[0.08, 0.12]} />
          <T.MeshBasicMaterial
            color={0xffd27a}
            transparent
            opacity={0.7}
          />
        </T.Mesh>
      {/each}
    </T.Group>
  </T.Group>
{/each}

<!-- Ground plane — receives the silhouette shadow line -->
<T.Mesh rotation.x={-Math.PI / 2} position={[0, -1.05, 0]}>
  <T.PlaneGeometry args={[80, 80]} />
  <T.MeshStandardMaterial color={0x02030a} roughness={1.0} />
</T.Mesh>
