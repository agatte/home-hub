import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { resolveBurgenerDeskStructure } from './burgener-desk-v1.js'
import { physicalWorldV1, resolveBedroomPhysicalWorld } from './physical-world-v1.js'

const physical = resolveBedroomPhysicalWorld()
const structure = resolveBurgenerDeskStructure(physical)

function minY(volume) { return volume.y - volume.d / 2 }
function maxY(volume) { return volume.y + volume.d / 2 }

describe('Burgener visible desk structure', () => {
  it('derives both manufacturer-sized modules only from Physical World v1', () => {
    expect(structure.main.top).toEqual(physical.objects.main.plan_bounds_gu)
    expect(structure.return.top).toEqual(physical.objects.return.plan_bounds_gu)
    expect(structure.main.top.w / structure.return.top.h).toBeCloseTo(62.99 / 39.37, 8)
    expect(structure.main.top.h / structure.return.top.w).toBeCloseTo(31.49 / 15.74, 8)
  })

  it('keeps the main open below its worktop with only steel supports', () => {
    expect(structure.main).not.toHaveProperty('cabinet')
    expect(structure.main.steelLegs).toHaveLength(4)
    expect(structure.main.blackSurface.w).toBeLessThan(structure.main.top.w)
    expect(structure.main.blackSurface.h).toBeLessThan(structure.main.top.h)
  })

  it('derives the complete return lower structure from its same resolved module', () => {
    const returnTop = structure.return.top
    const backPanel = structure.return.carcassPanels[0]
    expect(backPanel.d).toBeCloseTo(returnTop.h, 8)
    expect(minY(backPanel)).toBeCloseTo(returnTop.y, 8)
    expect(maxY(backPanel)).toBeCloseTo(returnTop.maxY, 8)
    expect(structure.return.cubbies).toHaveLength(3)
    expect(structure.return.drawers).toHaveLength(2)
    for (const part of [...structure.return.cubbies, ...structure.return.drawers]) {
      expect(minY(part)).toBeGreaterThanOrEqual(returnTop.y)
      expect(maxY(part)).toBeLessThanOrEqual(returnTop.maxY)
    }
  })

  it('keeps the cabinet exclusively on the return, with an explicit perpendicular seam', () => {
    expect(structure.return.carcassPanels).toHaveLength(4)
    expect(structure.return.cubbyDividers).toHaveLength(2)
    expect(structure.return.carcassPanels[0].w).toBeLessThanOrEqual(structure.return.top.w)
    expect(structure.return.seam).toEqual(expect.objectContaining({
      y: structure.main.top.y,
      length: structure.return.top.w,
      explicit: true,
    }))
  })

  it('keeps the projector supported on the return and compatibility-only anchors provisional', () => {
    const projector = physical.objects.projector.plan_bounds_gu
    const returnTop = structure.return.top
    expect(projector.x).toBeGreaterThanOrEqual(returnTop.x)
    expect(projector.maxX).toBeLessThanOrEqual(returnTop.maxX)
    expect(projector.y).toBeGreaterThanOrEqual(returnTop.y)
    expect(projector.maxY).toBeLessThanOrEqual(returnTop.maxY)
    expect(physicalWorldV1.compatibility_preview.not_physical_authority).toBe(true)
  })

  it('keeps legitimate black desk structure without decorative exterior edge strips', () => {
    const root = path.dirname(fileURLToPath(import.meta.url))
    const renderer = readFileSync(path.join(root, 'bedroom-v1.js'), 'utf8')
    expect(renderer).toContain("'Burgener bounded black central work surface'")
    expect(renderer).toContain("'Burgener rectangular steel leg'")
    expect(renderer).toContain("'Burgener black front apron'")
    expect(renderer).not.toContain("'Burgener main front edge'")
    expect(renderer).not.toContain("'Burgener return edge'")
    expect(structure.return.seam.explicit).toBe(true)
  })
})
