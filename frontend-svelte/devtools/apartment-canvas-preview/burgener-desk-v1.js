import { inchesToGu, resolveBedroomPhysicalWorld } from './physical-world-v1.js'

const TOP_THICKNESS_GU = 4.4
const RETURN_FACE_DEPTH_GU = 1.8
const RETURN_END_MARGIN_GU = 3.2
const RETURN_FACE_MARGIN_GU = 2.4

function rectangle(x, y, w, h) {
  return Object.freeze({ x, y, w, h, maxX: x + w, maxY: y + h })
}

function volume(x, y, z, w, d, h) {
  return Object.freeze({ x, y, z, w, d, h })
}

// Visible Burgener parts are derived from the two resolved manufacturer-sized
// modules. These values describe product segmentation only, never placement or
// physical authority.
export function resolveBurgenerDeskStructure(physical = resolveBedroomPhysicalWorld()) {
  const main = physical.objects.main.plan_bounds_gu
  const returnTop = physical.objects.return.plan_bounds_gu
  const topZ = physical.objects.main.dimensions_gu.high
  const undersideZ = topZ - TOP_THICKNESS_GU / 2
  const mainCenter = Object.freeze({ x: main.x + main.w / 2, y: main.y + main.h / 2 })
  const returnCenter = Object.freeze({ x: returnTop.x + returnTop.w / 2, y: returnTop.y + returnTop.h / 2 })
  const blackSurface = rectangle(
    mainCenter.x - main.w * 0.58 / 2,
    mainCenter.y - inchesToGu(19.68) / 2,
    main.w * 0.58,
    inchesToGu(19.68),
  )

  const cabinetSpan = rectangle(
    returnTop.x + RETURN_FACE_MARGIN_GU / 2,
    returnTop.y + RETURN_END_MARGIN_GU,
    returnTop.w - RETURN_FACE_MARGIN_GU,
    returnTop.h - RETURN_END_MARGIN_GU * 2,
  )
  const cubbyGap = 2.8
  const cubbyLength = (cabinetSpan.h - cubbyGap * 2) / 3
  const cubbyHeight = undersideZ * 0.42
  const cubbyCenterZ = undersideZ - cubbyHeight / 2 - 4
  const drawerGap = 2.8
  const drawerLength = (cabinetSpan.h - drawerGap) / 2
  const drawerHeight = undersideZ * 0.39
  const drawerCenterZ = drawerHeight / 2 + 5
  const returnFaceX = returnTop.maxX - RETURN_FACE_DEPTH_GU / 2

  const cubbies = Object.freeze(Array.from({ length: 3 }, (_, index) => volume(
    returnFaceX,
    cabinetSpan.y + cubbyLength / 2 + index * (cubbyLength + cubbyGap),
    cubbyCenterZ,
    RETURN_FACE_DEPTH_GU,
    cubbyLength,
    cubbyHeight,
  )))
  const drawers = Object.freeze(Array.from({ length: 2 }, (_, index) => volume(
    returnTop.maxX - 1.15,
    cabinetSpan.y + drawerLength / 2 + index * (drawerLength + drawerGap),
    drawerCenterZ,
    2.3,
    drawerLength,
    drawerHeight,
  )))

  return Object.freeze({
    topZ,
    undersideZ,
    main: Object.freeze({
      top: main,
      center: mainCenter,
      blackSurface,
      steelLegs: Object.freeze([
        volume(main.x + 8, main.y + 6.5, undersideZ / 2, 3.8, 3.8, undersideZ),
        volume(main.maxX - 8, main.y + 6.5, undersideZ / 2, 3.8, 3.8, undersideZ),
        volume(main.x + 8, main.maxY - 6.5, undersideZ / 2, 3.8, 3.8, undersideZ),
        volume(main.maxX - 8, main.maxY - 6.5, undersideZ / 2, 3.8, 3.8, undersideZ),
      ]),
      frontApron: volume(mainCenter.x, main.y + 6, undersideZ - 3.5, main.w - 14, 3.1, 7),
      sideApron: volume(main.maxX - 7, mainCenter.y, undersideZ - 3.5, 3.1, main.h - 12, 7),
    }),
    return: Object.freeze({
      top: returnTop,
      center: returnCenter,
      cabinetSpan,
      // Full-length dark carcass is intentionally panel-built so the front
      // remains genuinely segmented rather than reading as a solid block.
      carcassPanels: Object.freeze([
        volume(returnTop.x + 3.2, returnCenter.y, undersideZ / 2, 6.4, returnTop.h, undersideZ),
        volume(returnCenter.x, returnTop.y + 1.6, undersideZ / 2, returnTop.w - 1.4, 3.2, undersideZ),
        volume(returnCenter.x, returnTop.maxY - 1.6, undersideZ / 2, returnTop.w - 1.4, 3.2, undersideZ),
        volume(returnCenter.x, cabinetSpan.y + cabinetSpan.h / 2, cubbyHeight + 3, returnTop.w - 2.4, cabinetSpan.h, 2.6),
      ]),
      cubbyDividers: Object.freeze([1, 2].map((index) => volume(
        returnCenter.x,
        cabinetSpan.y + index * cubbyLength + (index - 0.5) * cubbyGap,
        cubbyCenterZ,
        returnTop.w - 2.4,
        cubbyGap,
        cubbyHeight,
      ))),
      cubbies,
      drawers,
      drawerPulls: Object.freeze(drawers.map((drawer) => volume(
        returnTop.maxX + 0.35,
        drawer.y,
        drawer.z,
        2.6,
        Math.min(15, drawer.d * 0.28),
        1.7,
      ))),
      // Separate tops deliberately meet on this perpendicular product seam.
      seam: Object.freeze({
        x: returnTop.x,
        y: main.y,
        length: returnTop.w,
        explicit: true,
      }),
    }),
  })
}
