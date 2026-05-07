<script>
  /**
   * FieldScene — the Threlte scene graph for FootballField.
   *
   * Lives inside the parent's <Canvas>. Renders the field plane,
   * yard lines, endzones, team labels, ball marker, and lighting.
   *
   * All inputs are props from the parent FootballField. Pure component.
   */
  import { T, useTask } from '@threlte/core'
  import { Text } from '@threlte/extras'

  /** @type {{ primary: string, secondary: string }} */
  export let theme

  /** @type {boolean} */
  export let hasGame = true

  /** @type {string} */
  export let opponentAbbr = 'OPP'

  /**
   * Target X position for the ball, in field-yard units.
   * Range: -50 (Colts goal line) .. +50 (Opp goal line).
   * @type {number}
   */
  export let targetBallX = 0

  /** @type {boolean} */
  export let reduceMotion = false

  // ---------------------------------------------------------------------
  // Field geometry constants. The mesh sits centered at origin with the
  // long axis along X. Y is up. 100 yards long, 53 wide.
  // ---------------------------------------------------------------------
  const FIELD_LENGTH = 100
  const FIELD_WIDTH = 53
  const ENDZONE_DEPTH = 10

  // Yard lines every 5 yards, drawn from -45 to +45 (excluding the
  // endzone boundaries themselves which are baked into the endzone planes).
  const YARD_LINE_X_VALUES = (() => {
    const values = []
    for (let x = -45; x <= 45; x += 5) values.push(x)
    return values
  })()

  // The 50 yard line wants to be a bit thicker for readability.
  const MIDFIELD_THICKNESS = 0.45
  const REGULAR_THICKNESS = 0.25
  const YARD_LINE_LIFT = 0.02 // tiny lift to prevent z-fighting with field

  // Field colors. Two slightly-different greens striped along the length
  // give the broadcast TV "mowed grass" look without a texture.
  const FIELD_GREEN_A = 0x2d5a3a
  const FIELD_GREEN_B = 0x356a44
  const STRIPE_COUNT = 10 // 10 alternating stripes across the play field

  // ---------------------------------------------------------------------
  // Ball marker animation. Smoothly eases toward targetBallX with a
  // mild bob so it feels alive even when the game is paused.
  // ---------------------------------------------------------------------
  let ballX = targetBallX
  let ballY = 1.0
  let bobPhase = 0
  // Springiness: higher = snappier. 4.0 reaches target in ~0.5s.
  const BALL_EASE_RATE = 4.0
  const BOB_AMPLITUDE = 0.18

  useTask((delta) => {
    if (reduceMotion) {
      ballX = targetBallX
      ballY = 1.0
      return
    }
    // Exponential ease toward target.
    const dx = targetBallX - ballX
    ballX += dx * Math.min(1, delta * BALL_EASE_RATE)
    bobPhase += delta * 2.4
    ballY = 1.0 + Math.sin(bobPhase) * BOB_AMPLITUDE
  })

  // Endzone center positions.
  const COLTS_ENDZONE_X = -(FIELD_LENGTH / 2 - ENDZONE_DEPTH / 2)
  const OPP_ENDZONE_X = FIELD_LENGTH / 2 - ENDZONE_DEPTH / 2

  // Field opacity dims when no live game (faded preview state).
  $: fieldOpacity = hasGame ? 1.0 : 0.55
</script>

<!--
  Camera. Top-down with a slight tilt so the labels and ball read with
  some depth. Perspective gives the broadcast feel; ortho would also
  work. The camera sits high above the field and slightly forward, then
  rotates manually rather than using lookAt so the orientation is
  deterministic across Threlte's render cycles.
  -->
<T.PerspectiveCamera
  makeDefault
  position={[0, 70, 18]}
  rotation={[-1.32, 0, 0]}
  fov={45}
  near={0.5}
  far={400}
/>

<!-- Lighting — ambient base + a directional sunbeam. Soft, broadcast-y. -->
<T.AmbientLight intensity={0.65} color={0xffffff} />
<T.DirectionalLight
  position={[20, 60, 30]}
  intensity={0.7}
  color={0xfff4d8}
/>
<T.DirectionalLight
  position={[-30, 40, -10]}
  intensity={0.25}
  color={0xb8c6ff}
/>

<!-- Stadium "ground" — large dark plane below the field for context. -->
<T.Mesh rotation.x={-Math.PI / 2} position={[0, -0.5, 0]}>
  <T.PlaneGeometry args={[200, 140]} />
  <T.MeshStandardMaterial color={0x0a0d14} roughness={1.0} />
</T.Mesh>

<!--
  Field base — the play area between the two endzones.
  Striped greens for that mowed-grass look.
-->
{#each Array(STRIPE_COUNT) as _, i}
  {@const stripeWidth = (FIELD_LENGTH - 2 * ENDZONE_DEPTH) / STRIPE_COUNT}
  {@const xCenter = -(FIELD_LENGTH / 2 - ENDZONE_DEPTH) + stripeWidth * (i + 0.5)}
  <T.Mesh
    rotation.x={-Math.PI / 2}
    position={[xCenter, 0, 0]}
  >
    <T.PlaneGeometry args={[stripeWidth, FIELD_WIDTH]} />
    <T.MeshStandardMaterial
      color={i % 2 === 0 ? FIELD_GREEN_A : FIELD_GREEN_B}
      roughness={0.95}
      transparent
      opacity={fieldOpacity}
    />
  </T.Mesh>
{/each}

<!-- Colts endzone (left). Tinted with theme.primary. -->
<T.Mesh
  rotation.x={-Math.PI / 2}
  position={[COLTS_ENDZONE_X, 0.005, 0]}
>
  <T.PlaneGeometry args={[ENDZONE_DEPTH, FIELD_WIDTH]} />
  <T.MeshStandardMaterial
    color={theme.primary}
    roughness={0.85}
    transparent
    opacity={fieldOpacity}
  />
</T.Mesh>

<!-- Opponent endzone (right). Neutral gray-white. -->
<T.Mesh
  rotation.x={-Math.PI / 2}
  position={[OPP_ENDZONE_X, 0.005, 0]}
>
  <T.PlaneGeometry args={[ENDZONE_DEPTH, FIELD_WIDTH]} />
  <T.MeshStandardMaterial
    color={0xd0d4dc}
    roughness={0.85}
    transparent
    opacity={fieldOpacity}
  />
</T.Mesh>

<!--
  Yard lines. Drawn as thin white planes flush with the field surface,
  perpendicular to the long axis. Midfield (x=0) is rendered thicker.
-->
{#each YARD_LINE_X_VALUES as x}
  {@const isMidfield = x === 0}
  {@const thickness = isMidfield ? MIDFIELD_THICKNESS : REGULAR_THICKNESS}
  <T.Mesh
    rotation.x={-Math.PI / 2}
    position={[x, YARD_LINE_LIFT, 0]}
  >
    <T.PlaneGeometry args={[thickness, FIELD_WIDTH]} />
    <T.MeshStandardMaterial
      color={0xf5f7fb}
      roughness={0.7}
      transparent
      opacity={fieldOpacity}
    />
  </T.Mesh>
{/each}

<!-- Endzone goal-line markers (white edge lines at ±40). -->
{#each [-(FIELD_LENGTH / 2 - ENDZONE_DEPTH), FIELD_LENGTH / 2 - ENDZONE_DEPTH] as goalX}
  <T.Mesh
    rotation.x={-Math.PI / 2}
    position={[goalX, YARD_LINE_LIFT, 0]}
  >
    <T.PlaneGeometry args={[0.4, FIELD_WIDTH]} />
    <T.MeshStandardMaterial
      color={0xffffff}
      roughness={0.7}
      transparent
      opacity={fieldOpacity}
    />
  </T.Mesh>
{/each}

<!--
  Endzone team labels. troika-three-text via @threlte/extras gives
  us 3D text without needing a font asset bundled in static/. Rotated
  90° on Y so the text reads correctly when the camera looks down.
-->
<Text
  text="IND"
  position={[COLTS_ENDZONE_X, 0.05, 0]}
  rotation={[-Math.PI / 2, 0, -Math.PI / 2]}
  fontSize={5}
  color="#ffffff"
  anchorX="center"
  anchorY="middle"
  outlineWidth={0.08}
  outlineColor="#000000"
/>
<Text
  text={opponentAbbr}
  position={[OPP_ENDZONE_X, 0.05, 0]}
  rotation={[-Math.PI / 2, 0, Math.PI / 2]}
  fontSize={5}
  color={theme.primary}
  anchorX="center"
  anchorY="middle"
  outlineWidth={0.08}
  outlineColor="#ffffff"
/>

<!--
  Ball marker. Brown sphere with a slight elongated scale so it reads
  as a football rather than a generic sphere. Tinted theme color
  faintly when Colts have it for a quick visual cue.
-->
<T.Group position={[ballX, ballY, 0]}>
  <T.Mesh scale={[1.4, 0.9, 0.9]}>
    <T.SphereGeometry args={[0.85, 24, 16]} />
    <T.MeshStandardMaterial
      color={0x6a3a1a}
      emissive={0x2a1808}
      emissiveIntensity={0.4}
      roughness={0.55}
      metalness={0.05}
    />
  </T.Mesh>
  <!-- Soft glow under the ball as a "this is the live ball" indicator -->
  <T.Mesh rotation.x={-Math.PI / 2} position={[0, -0.95, 0]}>
    <T.CircleGeometry args={[1.6, 24]} />
    <T.MeshBasicMaterial
      color={0xfff4d8}
      transparent
      opacity={hasGame ? 0.22 : 0.0}
      depthWrite={false}
    />
  </T.Mesh>
</T.Group>
