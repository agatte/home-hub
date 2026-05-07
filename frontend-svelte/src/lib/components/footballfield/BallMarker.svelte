<script>
  /**
   * BallMarker — animated football marker for the FieldScene.
   *
   * Brown sphere stretched into a football shape with a soft glow disc
   * underneath as a "live ball" indicator. Eases toward `targetBallX`
   * along the field's long axis with a mild bob. Honors prefers-
   * reduced-motion (snap to target, no bob).
   *
   * Pure prop-driven — no store imports, no API calls.
   */
  import { T, useTask } from '@threlte/core'

  /** Field-yard X position in [-50, +50]. -50 = Colts goal, +50 = Opp goal. */
  export let targetBallX = 0

  /** When true, hide the soft glow disc (no live game). */
  export let hasGame = true

  /** When true, snap to target with no bob. */
  export let reduceMotion = false

  // Springiness: higher = snappier. 4.0 reaches target in ~0.5s.
  const BALL_EASE_RATE = 4.0
  const BOB_AMPLITUDE = 0.18

  let ballX = targetBallX
  let ballY = 1.0
  let bobPhase = 0

  useTask((delta) => {
    if (reduceMotion) {
      ballX = targetBallX
      ballY = 1.0
      return
    }
    const dx = targetBallX - ballX
    ballX += dx * Math.min(1, delta * BALL_EASE_RATE)
    bobPhase += delta * 2.4
    ballY = 1.0 + Math.sin(bobPhase) * BOB_AMPLITUDE
  })
</script>

<T.Group position={[ballX, ballY, 0]}>
  <T.Mesh scale={[1.4, 0.9, 0.9]} castShadow>
    <T.SphereGeometry args={[0.85, 24, 16]} />
    <T.MeshStandardMaterial
      color={0x6a3a1a}
      emissive={0x2a1808}
      emissiveIntensity={0.4}
      roughness={0.55}
      metalness={0.05}
    />
  </T.Mesh>
  <!-- Soft glow under the ball as a "this is the live ball" indicator. -->
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
