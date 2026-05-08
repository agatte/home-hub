<script>
  /**
   * FieldSurface — painted football-field markings.
   *
   * Phase 1.6: the visible "ground" is no longer a PBR grass plane —
   * SkyDome's GroundedSkybox re-projects the HDRI's lower hemisphere
   * onto a 3D ground disc, so the captured stadium grass shows
   * through directly. This component now only renders the painted
   * markings layered on top of that HDRI ground:
   *
   *   - colored endzones (theme.primary / neutral white)
   *   - 19 yard-line decals (every 5 yards, midfield thicker)
   *   - 2 goal-line decals at ±40 X
   *   - perimeter outline (2 sidelines + 2 end lines) marking the
   *     field of play boundary
   *
   * Coordinate system: origin at midfield, X = long axis (Colts goal
   * at -50, opp goal at +50), Z = sideline width, Y = up.
   */
  import { T } from '@threlte/core'

  /** @type {{ primary: string, secondary: string }} */
  export let theme = { primary: '#002C5F', secondary: '#FFFFFF' }

  /** Field opacity dims when no live game (faded preview state). */
  export let opacity = 1.0

  // Painted-field geometry. Real American football is 100×53.3 yards;
  // BallMarker uses X ∈ [-50, +50] for possession-driven positions.
  const FIELD_LENGTH = 100
  const FIELD_WIDTH = 53
  const ENDZONE_DEPTH = 10
  const YARD_LINE_LIFT = 0.02
  const COLTS_ENDZONE_X = -(FIELD_LENGTH / 2 - ENDZONE_DEPTH / 2)
  const OPP_ENDZONE_X = FIELD_LENGTH / 2 - ENDZONE_DEPTH / 2

  const YARD_LINE_X_VALUES = (() => {
    const v = []
    for (let x = -45; x <= 45; x += 5) v.push(x)
    return v
  })()

  const MIDFIELD_THICKNESS = 0.45
  const REGULAR_THICKNESS = 0.25

  // Field-perimeter outline. Sidelines run the long axis at Z=±26.5
  // (full 100yd along X, including both endzones); end lines close
  // the rectangle at X=±50 (full 53yd along Z). Thicker than yard
  // lines (0.5 vs 0.25) — perimeter reads as more substantial.
  const SIDELINE_THICKNESS = 0.5
  const SIDELINE_Z = FIELD_WIDTH / 2
  const END_LINE_X = FIELD_LENGTH / 2
</script>

<!-- Colts endzone (left, theme-tinted). -->
<T.Mesh
  rotation.x={-Math.PI / 2}
  position={[COLTS_ENDZONE_X, 0.005, 0]}
  receiveShadow
>
  <T.PlaneGeometry args={[ENDZONE_DEPTH, FIELD_WIDTH]} />
  <T.MeshStandardMaterial
    color={theme.primary}
    roughness={0.85}
    transparent
    opacity={opacity}
  />
</T.Mesh>

<!-- Opponent endzone (right, neutral gray-white). -->
<T.Mesh
  rotation.x={-Math.PI / 2}
  position={[OPP_ENDZONE_X, 0.005, 0]}
  receiveShadow
>
  <T.PlaneGeometry args={[ENDZONE_DEPTH, FIELD_WIDTH]} />
  <T.MeshStandardMaterial
    color={0xd0d4dc}
    roughness={0.85}
    transparent
    opacity={opacity}
  />
</T.Mesh>

<!-- Yard lines every 5 yards from -45 to +45. Midfield (x=0) thicker. -->
{#each YARD_LINE_X_VALUES as x}
  {@const isMidfield = x === 0}
  {@const thickness = isMidfield ? MIDFIELD_THICKNESS : REGULAR_THICKNESS}
  <T.Mesh rotation.x={-Math.PI / 2} position={[x, YARD_LINE_LIFT, 0]}>
    <T.PlaneGeometry args={[thickness, FIELD_WIDTH]} />
    <T.MeshStandardMaterial
      color={0xf5f7fb}
      roughness={0.7}
      transparent
      opacity={opacity}
    />
  </T.Mesh>
{/each}

<!-- Goal lines at the field/endzone boundaries (±40). -->
{#each [-(FIELD_LENGTH / 2 - ENDZONE_DEPTH), FIELD_LENGTH / 2 - ENDZONE_DEPTH] as goalX}
  <T.Mesh rotation.x={-Math.PI / 2} position={[goalX, YARD_LINE_LIFT, 0]}>
    <T.PlaneGeometry args={[0.4, FIELD_WIDTH]} />
    <T.MeshStandardMaterial
      color={0xffffff}
      roughness={0.7}
      transparent
      opacity={opacity}
    />
  </T.Mesh>
{/each}

<!-- Sidelines (long sides at Z=±26.5, span full 100yd along X). -->
{#each [-SIDELINE_Z, SIDELINE_Z] as z}
  <T.Mesh rotation.x={-Math.PI / 2} position={[0, YARD_LINE_LIFT, z]}>
    <T.PlaneGeometry args={[FIELD_LENGTH, SIDELINE_THICKNESS]} />
    <T.MeshStandardMaterial
      color={0xffffff}
      roughness={0.7}
      transparent
      opacity={opacity}
    />
  </T.Mesh>
{/each}

<!-- End lines (short sides at X=±50, span full 53yd along Z). -->
{#each [-END_LINE_X, END_LINE_X] as x}
  <T.Mesh rotation.x={-Math.PI / 2} position={[x, YARD_LINE_LIFT, 0]}>
    <T.PlaneGeometry args={[SIDELINE_THICKNESS, FIELD_WIDTH]} />
    <T.MeshStandardMaterial
      color={0xffffff}
      roughness={0.7}
      transparent
      opacity={opacity}
    />
  </T.Mesh>
{/each}
