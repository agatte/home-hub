<script>
  /**
   * LightTowers — 4 corner stadium light towers.
   *
   * Each tower is a tall pole with an emissive lamp head + a
   * PointLight for actual illumination. The emissive lamp triggers
   * BloomEffect (in PostFX.svelte) for the glowing-bulb look.
   *
   * Positions are tuned for the Awbmegames stadium model bounds
   * after our Y-rotation and 0.81 scale (bowl extends ±104 X × ±82
   * Z). Towers sit just inside the bowl's corners so they read as
   * "stadium light fixtures" rather than floating lights.
   *
   * Phase 2 ships these always-on. Phase 2.5 will gate them by
   * `kickoff_utc` time-of-day so they only illuminate for evening
   * and night games.
   */
  import { T } from '@threlte/core'

  /** Pole height in yards (also Y of the lamp head). */
  const POLE_HEIGHT = 60

  /** PointLight peak intensity. Three.js r155+ uses physically-correct
   *  units, so this needs to be substantial to read in a 250×150 yd
   *  field area. */
  const LAMP_INTENSITY = 800

  /** PointLight falloff distance. Beyond this the contribution is 0. */
  const LAMP_DISTANCE = 200

  /** Warm broadcast-stadium-lamp white. */
  const LAMP_COLOR = 0xfff4e0

  // 4 corners. X axis is field long axis (±100 endline area).
  // Z axis is sideline width (±82 bowl wall).
  const TOWER_POSITIONS = [
    [-95, 0, -75],
    [+95, 0, -75],
    [-95, 0, +75],
    [+95, 0, +75],
  ]
</script>

{#each TOWER_POSITIONS as [x, _y, z]}
  <T.Group position={[x, 0, z]}>
    <!-- Pole — thin tall cylinder, dark metal. -->
    <T.Mesh position={[0, POLE_HEIGHT / 2, 0]} castShadow>
      <T.CylinderGeometry args={[0.4, 0.4, POLE_HEIGHT, 8]} />
      <T.MeshStandardMaterial color={0x3a3d44} roughness={0.6} metalness={0.4} />
    </T.Mesh>

    <!-- Lamp head — emissive box. Bloom picks this up. -->
    <T.Mesh position={[0, POLE_HEIGHT, 0]} castShadow>
      <T.BoxGeometry args={[3, 1.2, 3]} />
      <T.MeshStandardMaterial
        color={0x222222}
        emissive={LAMP_COLOR}
        emissiveIntensity={6}
        roughness={0.5}
        metalness={0.2}
      />
    </T.Mesh>

    <!-- Actual scene illumination from the lamp head. -->
    <T.PointLight
      position={[0, POLE_HEIGHT - 0.3, 0]}
      color={LAMP_COLOR}
      intensity={LAMP_INTENSITY}
      distance={LAMP_DISTANCE}
      decay={1.5}
    />
  </T.Group>
{/each}
