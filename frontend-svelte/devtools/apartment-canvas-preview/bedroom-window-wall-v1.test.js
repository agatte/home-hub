import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import geometryScene from '../apartment-whitebox/generated/geometry-scene.json'
import { adaptGeometryScene } from '../apartment-whitebox/adapter.js'
import { BEDROOM_WINDOW_WALL_REALIZATION_V1, bedroomWindowWallClosureFootprint } from './bedroom-window-wall-v1.js'
import { BEDROOM_CARPET_COVERAGE_V1 } from './furniture-v1.js'
import { resolveBedroomPhysicalWorld } from './physical-world-v1.js'

describe('Bedroom flat window-wall realization v1', () => {
  it('keeps glazing recessed while the below-window closure reaches the finished room-side wall plane', () => {
    const data = adaptGeometryScene(geometryScene)
    const windows = data.openings.filter((opening) => opening.sourceApertureId?.startsWith('bedroom_window_'))

    expect(data.fingerprint).toBe('ba9270ddd772aa859dca2e155e14a54c8d1eccb3daeb869e6301780bbdd4cf43')
    expect(BEDROOM_WINDOW_WALL_REALIZATION_V1.classification).toBe('presentation_only_recessed_glazing_with_flush_below_sill_wall')
    expect(BEDROOM_WINDOW_WALL_REALIZATION_V1.finishedRoomSideYGu).toBe(65.91)
    expect(windows).toHaveLength(2)
    for (const opening of windows) {
      const closure = bedroomWindowWallClosureFootprint(opening)
      expect(opening.segment[0].y).toBeCloseTo(52.88852725793328, 10)
      expect(closure[0].y).toBe(opening.segment[0].y)
      expect(closure[1].y).toBe(opening.segment[1].y)
      expect(closure[2].y).toBe(BEDROOM_WINDOW_WALL_REALIZATION_V1.finishedRoomSideYGu)
      expect(closure[3].y).toBe(BEDROOM_WINDOW_WALL_REALIZATION_V1.finishedRoomSideYGu)
      expect(BEDROOM_CARPET_COVERAGE_V1.y).toBeLessThanOrEqual(BEDROOM_WINDOW_WALL_REALIZATION_V1.finishedRoomSideYGu)
      expect(BEDROOM_CARPET_COVERAGE_V1.y + BEDROOM_CARPET_COVERAGE_V1.h).toBeGreaterThan(BEDROOM_WINDOW_WALL_REALIZATION_V1.finishedRoomSideYGu)
    }
    const sill = resolveBedroomPhysicalWorld().architecture.windowSill.plan_bounds_gu
    expect(sill.y).toBeCloseTo(windows[0].segment[0].y, 10)
    expect(sill.maxY).toBeGreaterThan(BEDROOM_WINDOW_WALL_REALIZATION_V1.finishedRoomSideYGu)
    const renderer = readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), 'main-v2.js'), 'utf8')
    expect(renderer).toContain('bedroomWindowWallClosureFootprint(opening)')
  })
})
