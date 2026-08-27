import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { resolveBedroomPhysicalWorld } from './physical-world-v1.js'
import { resolveBurgenerDeskStructure } from './burgener-desk-v1.js'
import { resolveBedroomWorkstationAccessories } from './workstation-accessories-v1.js'

const physical = resolveBedroomPhysicalWorld()
const accessories = resolveBedroomWorkstationAccessories(physical)

function contains(outer, inner) {
  return inner.x >= outer.x && inner.maxX <= outer.maxX && inner.y >= outer.y && inner.maxY <= outer.maxY
}

function overlaps(a, b) {
  return a.x < b.maxX && a.maxX > b.x && a.y < b.maxY && a.maxY > b.y
}

describe('Bedroom workstation accessory preview anchors', () => {
  it('keeps the PC under the main on the return/junction side, not in the return cabinet', () => {
    const main = physical.objects.main.plan_bounds_gu
    const returnDesk = physical.objects.return.plan_bounds_gu
    const pc = accessories.pc.bounds
    expect(accessories.pc.relationship).toBe('under_main_return_junction_side')
    expect(contains(main, pc)).toBe(true)
    expect(pc.x + pc.w / 2).toBeLessThan(main.x + main.w / 2)
    expect(pc.y).toBeGreaterThanOrEqual(returnDesk.maxY)
    expect(pc.y - main.y).toBeLessThan(5)
    expect(pc.w).toBeGreaterThanOrEqual(30)
    expect(pc.h).toBeGreaterThanOrEqual(55)
    expect(accessories.pc.height_gu).toBeGreaterThanOrEqual(70)
  })

  it('centers the monitor at the main rear edge and keeps the Yeti separately to monitor-right and roomward', () => {
    const main = physical.objects.main.plan_bounds_gu
    for (const key of ['monitor', 'microphone', 'leftLamp', 'headphones', 'alexa']) {
      expect(contains(main, accessories[key].bounds)).toBe(true)
      expect(accessories[key].status).toBe('provisional_review_required')
    }
    const monitor = accessories.monitor.bounds
    const yeti = accessories.microphone.bounds
    expect(accessories.monitor.local_anchor).toBe('main_center_rear')
    expect(monitor.x + monitor.w / 2).toBeCloseTo(main.x + main.w / 2)
    expect(accessories.microphone.local_anchor).toBe('monitor_right_clearance_forward')
    // Raw x is reflected: lower raw x presents farther right on the desk.
    expect(yeti.x + yeti.w / 2).toBeLessThan(monitor.x + monitor.w / 2)
    expect(yeti.maxX).toBeLessThan(monitor.x)
    expect(yeti.y + yeti.h / 2).toBeLessThan(monitor.y + monitor.h / 2)
    expect(overlaps(yeti, monitor)).toBe(false)
  })

  it('keeps the right lamp base on the main rear-right before the return, oriented inward toward chair/front-center', () => {
    const main = physical.objects.main.plan_bounds_gu
    const returnDesk = physical.objects.return.plan_bounds_gu
    const lamp = accessories.rightLamp
    expect(contains(main, lamp.bounds)).toBe(true)
    expect(overlaps(lamp.bounds, returnDesk)).toBe(false)
    expect(lamp.bounds.y).toBeGreaterThan(main.y + main.h * 0.7)
    expect(lamp.bounds.x + lamp.bounds.w / 2).toBeLessThan(accessories.microphone.bounds.x + accessories.microphone.bounds.w / 2)
    expect(lamp.relationship).toBe('main_rear_right_before_return_diagonal_toward_chair')
    expect(lamp.local_anchor).toBe('main_rear_right_before_return')
    expect(lamp.local_left_open_u).toBe(0.86)
    expect(main.w * (lamp.local_left_open_u - 0.84)).toBeGreaterThan(0)
    expect(main.w * (lamp.local_left_open_u - 0.84)).toBeLessThan(5)
    expect(lamp.orientation).toEqual({
      base_long_axis: 'rear_right_to_front_center',
      stem_anchor: 'rear_right',
      shade_direction: 'inward_front_center',
    })
    expect(lamp.yaw_radians).toBeCloseTo(-Math.PI / 4)
    expect(lamp.stem_local_x_gu).toBeLessThan(lamp.shade_local_x_gu)
  })

  it('places the Alexa puck to the visual left of the fabric lamp under the accepted reflection', () => {
    const alexaCenter = accessories.alexa.bounds.x + accessories.alexa.bounds.w / 2
    const lampCenter = accessories.leftLamp.bounds.x + accessories.leftLamp.bounds.w / 2
    expect(accessories.alexa.relationship).toBe('main_rear_left_of_fabric_lamp')
    expect(accessories.alexa.local_anchor).toBe('left_of_left_lamp')
    expect(alexaCenter).toBeGreaterThan(lampCenter)
  })

  it('preserves the approved PC tower placement while desktop accessories move independently', () => {
    const main = physical.objects.main.plan_bounds_gu
    const returnDesk = physical.objects.return.plan_bounds_gu
    expect(accessories.pc.bounds).toEqual({
      x: returnDesk.maxX - 28.5,
      y: main.y + 3.5,
      w: 31,
      h: 57,
      maxX: returnDesk.maxX + 2.5,
      maxY: main.y + 60.5,
    })
    expect(accessories.pc.height_gu).toBe(72)
  })

  it('keeps PC presentation detail bounded to its accepted tower envelope', () => {
    const root = path.dirname(fileURLToPath(import.meta.url))
    const renderer = readFileSync(path.join(root, 'bedroom-v1.js'), 'utf8')
    expect(renderer).toContain("'PC tower inset base foot'")
    expect(renderer).toContain("'PC tower internal dark component mass'")
    expect(renderer).toContain('f.y + 0.3')
    expect(renderer).toContain('f.maxX - 0.28')
    expect(renderer).not.toContain('f.y - 0.36')
    expect(renderer).not.toContain('f.x + f.w + 0.33')
  })

  it('leaves the chair in the main working span and physical desk/projector authority untouched', () => {
    const main = physical.objects.main.plan_bounds_gu
    expect(accessories.chair.bounds.maxY).toBeLessThanOrEqual(main.y)
    expect(accessories.chair.relationship).toBe('main_front_centered_working_knee_span')
    expect(resolveBurgenerDeskStructure(physical).main.top).toEqual(main)
    expect(physical.objects.projector.plan_bounds_gu.y).toBeGreaterThanOrEqual(physical.objects.return.plan_bounds_gu.y)
  })

  it('removes legacy annotation and blocker rendering from the desk-local accessory path', () => {
    const root = path.dirname(fileURLToPath(import.meta.url))
    const renderer = readFileSync(path.join(root, 'bedroom-v1.js'), 'utf8')
    const furniture = readFileSync(path.join(root, 'furniture-v1.js'), 'utf8')
    expect(renderer).toContain("resolveBedroomWorkstationAccessories(bedroomPhysical)")
    expect(renderer).not.toContain("annotation('bedroom.monitor')")
    expect(renderer).not.toContain("annotation('bedroom.microphone')")
    expect(furniture).toContain("'bedroom.pc'")
  })
})
