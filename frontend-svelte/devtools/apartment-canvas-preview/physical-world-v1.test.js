import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { inchesToGu, physicalWorldV1, resolveBedroomPhysicalWorld } from './physical-world-v1.js'

const resolved = resolveBedroomPhysicalWorld()

function ratio(numerator, denominator) {
  return numerator / denominator
}

describe('Bedroom Physical World v1', () => {
  it('uses exactly one provisional apartment-wide calibration for all physical axes', () => {
    const calibration = physicalWorldV1.calibrations.apartment_physical_v1
    expect(calibration.gu_per_in).toBe(3.39)
    expect(calibration.tolerance_gu_per_in).toBe(0.05)
    for (const object of Object.values(resolved.objects).filter((item) => item.calibration_ref)) {
      expect(object.calibration_ref).toBe('apartment_physical_v1')
    }
    expect(inchesToGu(1)).toBe(3.39)
  })

  it('derives physical dimensions with the same calibration on X, Y, and Z', () => {
    expect(resolved.objects.bed.dimensions_gu.long).toBeCloseTo(284.76, 10)
    expect(resolved.objects.bed.dimensions_gu.wide).toBeCloseTo(217.299, 10)
    expect(resolved.objects.main.dimensions_gu.long).toBeCloseTo(213.5361, 10)
    expect(resolved.objects.main.dimensions_gu.deep).toBeCloseTo(106.7511, 10)
    expect(resolved.objects.main.dimensions_gu.high).toBeCloseTo(100.0728, 10)
    expect(resolved.objects.return.dimensions_gu.long).toBeCloseTo(133.4643, 10)
    expect(resolved.objects.return.dimensions_gu.deep).toBeCloseTo(53.3586, 10)
    expect(resolved.objects.return.dimensions_gu.high).toBeCloseTo(100.0728, 10)
    expect(resolved.objects.main.dimensions_gu.high / 29.52).toBeCloseTo(3.39, 10)
  })

  it('preserves every manufacturer product ratio without independent axis stretching', () => {
    const { bed, main, return: returnDesk } = resolved.objects
    expect(ratio(bed.dimensions_gu.long, bed.dimensions_gu.wide)).toBeCloseTo(ratio(84, 64.1), 10)
    expect(ratio(main.dimensions_gu.long, main.dimensions_gu.deep)).toBeCloseTo(ratio(62.99, 31.49), 10)
    expect(ratio(returnDesk.dimensions_gu.long, returnDesk.dimensions_gu.deep)).toBeCloseTo(ratio(39.37, 15.74), 10)
    expect(ratio(returnDesk.dimensions_gu.long, main.dimensions_gu.long)).toBeCloseTo(ratio(39.37, 62.99), 10)
    expect(ratio(returnDesk.dimensions_gu.deep, main.dimensions_gu.deep)).toBeCloseTo(ratio(15.74, 31.49), 10)
  })

  it('derives a perpendicular, distinct workstation seam with cabinet support only on the return', () => {
    const { main, return: returnDesk } = resolved.objects
    expect(main.orientation.long_axis).toBe('+x')
    expect(returnDesk.orientation.long_axis).toBe('+y')
    expect(returnDesk.plan_bounds_gu.maxY).toBeCloseTo(main.plan_bounds_gu.y, 10)
    expect(main.placement.anchors.some((anchor) => anchor.kind === 'seam_junction_relative')).toBe(true)
    expect(returnDesk.orientation.cabinet_face).toBe('+x')
    expect(main).not.toHaveProperty('cabinet_face')
    expect(returnDesk.physical_dimensions_in).toEqual({ long: 39.37, deep: 15.74, high: 29.52 })
  })

  it('keeps the local window sill separate elevated architecture without treating it as a floor-level bed collision', () => {
    const { bed, return: returnDesk } = resolved.objects
    const sill = resolved.architecture.windowSill
    expect(sill.classification).toBe('fixed_architecture')
    expect(sill.host_relationship.target).toBe('bedroom window opening')
    expect(sill.host_relationship.relation).toBe('local elevated sill projects outward into the room from the flat room-side window-wall plane')
    expect(sill.extent.must_not_be_interpreted_as).toBe('full bedroom wall feature')
    expect(sill.plan_bounds_gu.w).toBeLessThan(413.35)
    expect(bed.placement.anchors).toContainEqual(expect.objectContaining({
      target: 'bedroom.window_sill', relation: 'bed is directly adjacent to / may sit underneath the elevated sill projection; exact XY overlap is unresolved',
    }))
    expect(bed.placement.unresolved).toContainEqual(expect.objectContaining({
      fact: 'bed_to_sill_xy_overlap', status: 'unmeasured',
      must_not_be_interpreted_as: 'floor_level_collision_or_required_non_overlap',
    }))
    expect(sill.preview_placement.status).toBe('provisional_review_required')
    expect(sill.preview_placement.top_z_gu).toBeGreaterThan(sill.preview_placement.thickness_gu)
    expect(sill.unresolved.map((item) => item.fact)).toEqual(expect.arrayContaining([
      'exact_projection_depth', 'exact_left_right_overhang', 'exact_vertical_section',
    ]))
    expect(returnDesk.id).toBe('bedroom.burgener_return')
    expect(returnDesk).not.toHaveProperty('classification')
  })

  it('keeps the Braya renderer bound only to the accepted bed physical envelope', () => {
    const root = path.dirname(fileURLToPath(import.meta.url))
    const renderer = readFileSync(path.join(root, 'bedroom-v1.js'), 'utf8')
    const { bed } = resolved.objects
    expect(bed.plan_bounds_gu).toEqual({
      x: 13.83, y: 70, w: inchesToGu(84), h: inchesToGu(64.1),
      maxX: 298.59, maxY: 287.299,
    })
    expect(bed.orientation).toEqual({ long_axis: '+x', wide_axis: '+y', headboard_face: '-x' })
    expect(renderer).toContain('const f = bedroomPhysical.objects.bed.plan_bounds_gu')
    expect(renderer).toContain("'Braya substantial upholstered headboard backing'")
    expect(renderer).toContain("'Braya clearly inset mattress sidewall'")
    expect(renderer).toContain('function softPillowGeometry')
    expect(renderer).toContain('softPillowGeometry(f.w * 0.215, f.h * 0.29, height)')
    expect(renderer).toContain('pillow.position.set(f.x + f.w * 0.29, y, 73.8)')
    expect(renderer).toContain('function drapedDuvetGeometry')
    expect(renderer).not.toContain("'Braya contained layered duvet'")
    expect(renderer).not.toContain("footprint(data, 'bedroom.bed')")
  })

  it('keeps the provisional projector entirely supported by the return', () => {
    const { projector, return: returnDesk } = resolved.objects
    const support = returnDesk.plan_bounds_gu
    const projection = projector.plan_bounds_gu
    expect(projection.x).toBeGreaterThanOrEqual(support.x)
    expect(projection.maxX).toBeLessThanOrEqual(support.maxX)
    expect(projection.y).toBeGreaterThanOrEqual(support.y)
    expect(projection.maxY).toBeLessThanOrEqual(support.maxY)
    expect(projector.placement.status).toBe('provisional_review_required')
  })

  it('keeps unmeasured placement facts explicit and does not read migrated dimensions from blockers', () => {
    const source = JSON.stringify(physicalWorldV1)
    expect(source).toContain('"status":"unmeasured"')
    expect(source).toContain('must_not_be_interpreted_as')
    expect(source).not.toContain('geometry-scene.json')
    expect(resolved.objects.bed.plan_bounds_gu.w).toBe(inchesToGu(84))
    expect(resolved.objects.bed.plan_bounds_gu.h).toBe(inchesToGu(64.1))
    expect(resolved.objects.main.plan_bounds_gu.h).toBe(inchesToGu(31.49))
    expect(resolved.objects.return.plan_bounds_gu.w).toBe(inchesToGu(15.74))
    const renderer = readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), 'bedroom-v1.js'), 'utf8')
    expect(renderer).not.toContain("footprint(data, 'bedroom.bed')")
    expect(renderer).not.toContain("footprint(data, 'bedroom.desk_main')")
    expect(renderer).not.toContain("footprint(data, 'bedroom.desk_return')")
  })
})
