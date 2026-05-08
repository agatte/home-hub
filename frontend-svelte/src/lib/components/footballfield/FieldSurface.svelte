<script>
  /**
   * FieldSurface — the playing field, endzones, yard lines, goal lines.
   *
   * PBR grass plane (color/normal/roughness from Poly Haven leafy_grass)
   * tiled across an extended out-of-bounds surface (250×150 yd) so the
   * grass blends visually outward to meet the HDRI horizon without a
   * hard seam. Theme-tinted endzones and white yard-line decals layer
   * on top at the standard football-field 100×53 positions in the
   * middle of the wider grass.
   *
   * Coordinate system: origin at midfield, X = long axis (Colts goal at
   * -50, opp goal at +50), Z = sideline width, Y = up.
   */
  import { T } from '@threlte/core'
  import { useTexture } from '@threlte/extras'
  import { RepeatWrapping } from 'three'

  /** @type {{ primary: string, secondary: string }} */
  export let theme = { primary: '#002C5F', secondary: '#FFFFFF' }

  /** Field opacity dims when no live game (faded preview state). */
  export let opacity = 1.0

  // Painted-field geometry — yard lines, endzones, goal lines all
  // derive from these. Real American football is 100×53.3 yards;
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

  // Grass plane is wider than the painted field so the surrounding
  // surface blends outward to meet the HDRI horizon. ~2 yards per
  // tile keeps the leafy_grass detail readable without obvious
  // repetition (textures are 2K source).
  const GRASS_PLANE_LENGTH = 250
  const GRASS_PLANE_WIDTH = 150
  const GRASS_REPEAT_X = 125
  const GRASS_REPEAT_Z = 75

  // Load the 3 PBR maps as a record. Returns an async store keyed by
  // the same names; transform sets RepeatWrapping + tiling on each.
  const grass = useTexture(
    {
      map: '/3d/textures/grass-color.jpg',
      normalMap: '/3d/textures/grass-normal.jpg',
      roughnessMap: '/3d/textures/grass-roughness.jpg',
    },
    {
      transform: (texture) => {
        texture.wrapS = RepeatWrapping
        texture.wrapT = RepeatWrapping
        texture.repeat.set(GRASS_REPEAT_X, GRASS_REPEAT_Z)
        return texture
      },
    },
  )
</script>

{#if $grass}
  <!--
    Extended grass plane (250×150 yd) — covers the painted field plus
    a generous out-of-bounds margin so the grass blends out to the
    HDRI horizon without a visible seam. PBR with full texture set,
    receives shadows from the sun light.
  -->
  <T.Mesh rotation.x={-Math.PI / 2} receiveShadow>
    <T.PlaneGeometry args={[GRASS_PLANE_LENGTH, GRASS_PLANE_WIDTH]} />
    <T.MeshStandardMaterial
      map={$grass.map}
      normalMap={$grass.normalMap}
      roughnessMap={$grass.roughnessMap}
      transparent
      opacity={opacity}
    />
  </T.Mesh>
{/if}

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
