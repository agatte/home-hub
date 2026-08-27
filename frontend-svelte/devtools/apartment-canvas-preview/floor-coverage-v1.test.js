import { describe, expect, it } from 'vitest'
import { BEDROOM_CARPET_COVERAGE_V1 } from './furniture-v1.js'
import { resolveBedroomPhysicalWorld } from './physical-world-v1.js'

describe('Bedroom carpet coverage v1', () => {
  it('covers continuously beneath the local window sill without changing physical geometry', () => {
    const sill = resolveBedroomPhysicalWorld().architecture.windowSill.plan_bounds_gu
    const carpet = BEDROOM_CARPET_COVERAGE_V1

    expect(carpet.y).toBeLessThanOrEqual(sill.y)
    expect(carpet.x).toBeLessThanOrEqual(sill.x)
    expect(carpet.x + carpet.w).toBeGreaterThanOrEqual(sill.maxX)
    expect(carpet.y + carpet.h).toBeCloseTo(534.6, 10)
  })
})
