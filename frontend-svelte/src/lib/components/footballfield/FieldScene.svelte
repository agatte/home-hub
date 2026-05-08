<script>
  /**
   * FieldScene — top-level composition of the football field 3D scene.
   *
   * Phase 1a (current): HDRI environment for sky + image-based
   * lighting, PBR grass field surface, broadcast-camera angle, ball
   * marker. The "everything is black" void is replaced by the Poly
   * Haven stadium HDRI.
   *
   * Phase 1b (next): drop in a glTF stadium model + instanced crowd
   * once a model is selected. The composition is modular so adding
   * those is a one-component import.
   *
   * Phases 2+: see ~/.claude/plans/okay-with-our-agents-hashed-popcorn.md
   *   - phase 2: stadium light towers, god rays, bloom, weather sky
   *   - phase 3: cinematic camera dynamics
   *   - phase 4: yard numbers, hash marks, midfield logo, confetti
   */
  import { T } from '@threlte/core'
  import BallMarker from './BallMarker.svelte'
  import BroadcastCamera from './BroadcastCamera.svelte'
  import FieldSurface from './FieldSurface.svelte'
  import SkyDome from './SkyDome.svelte'
  import StadiumModel from './StadiumModel.svelte'

  /** @type {{ primary: string, secondary: string }} */
  export let theme

  /** @type {boolean} */
  export let hasGame = true

  /**
   * Opponent abbreviation. Currently unused at the scene level (the
   * +page.svelte HUD owns scoreboard chrome) but kept on the prop
   * surface so phase 4's endzone painted-text can pick it up without
   * a re-plumb.
   */
  // eslint-disable-next-line no-unused-vars
  export let opponentAbbr = 'OPP'
  opponentAbbr;

  /** Field-yard X position for the ball, in [-50, +50]. */
  export let targetBallX = 0

  /** True when prefers-reduced-motion is set. */
  export let reduceMotion = false

  // Field opacity dims when no live game (faded preview state).
  $: fieldOpacity = hasGame ? 1.0 : 0.55
</script>

<!-- Camera. Static broadcast preset for phase 1; phase 3 swaps for cinematic camera-controls. -->
<BroadcastCamera {reduceMotion} />

<!--
  HDRI environment. Loads the Poly Haven Stadium 01 equirect map and
  applies it as both scene background AND IBL source for PBR materials.
  This is the single biggest visual upgrade vs the prior all-black scene.
-->
<SkyDome />

<!--
  Sun. Drives shadow direction; the HDRI's IBL handles diffuse fill on
  PBR materials, so we only need one explicit directional light. Position
  matches the Stadium 01 HDRI's roughly-east sun for visual consistency
  between the cast shadows and the baked HDRI lighting.
-->
<T.DirectionalLight
  position={[40, 80, 25]}
  intensity={1.4}
  color={0xffeacc}
  castShadow
  shadow.mapSize.width={2048}
  shadow.mapSize.height={2048}
  shadow.camera.near={1}
  shadow.camera.far={300}
  shadow.camera.left={-80}
  shadow.camera.right={80}
  shadow.camera.top={80}
  shadow.camera.bottom={-80}
  shadow.bias={-0.0005}
/>

<!--
  Low-intensity ambient lift. The HDRI's environment map already
  supplies most of the indirect light via IBL on the PBR materials, so
  this is just a small nudge to keep cast-shadow blacks readable rather
  than crushed.
-->
<T.AmbientLight intensity={0.15} color={0xffffff} />

<!--
  Stadium bowl. Awbmegames Low Poly Football Stadium (CC-BY-4.0,
  Sketchfab). Model's native long axis is Z, ~123 units; our field's
  long axis is X, 100 yards. We Y-rotate 90° to align long axes,
  scale 0.81 so the model's painted field matches our 100-yard X
  span, and lower by 2.5 so the model's painted field surface sits
  just under our PBR FieldSurface (model field is ~11 yards wider
  along Z than ours, so its sideline area peeks out as the natural
  out-of-bounds surface around our painted field).
-->
<StadiumModel
  rotation={[0, Math.PI / 2, 0]}
  scale={0.81}
  position={[0, -2.5, 0]}
/>

<!-- Playing field, endzones, yard lines, goal lines (PBR grass). -->
<FieldSurface {theme} opacity={fieldOpacity} />

<!-- Live ball marker (phase 1b will animate yard-line position from PlayEvent). -->
<BallMarker {targetBallX} {hasGame} {reduceMotion} />
