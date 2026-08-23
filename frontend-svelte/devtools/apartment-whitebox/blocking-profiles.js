/**
 * Inspector-only physical blocking profiles.
 *
 * Object rectangles are supplied by GeometryScene inspection annotations at
 * runtime.  This table deliberately contains no plan-space coordinates and
 * no orientation transforms: each accepted rectangle already is the final
 * occupied top-down footprint.  All z values and silhouettes are provisional
 * visual-review choices, not a durable furniture or object-z authority.
 */

const PRIMARY_IDS = [
  'bedroom.bed', 'bedroom.desk_main', 'bedroom.desk_return', 'bedroom.chair',
  'living.couch', 'living.coffee_table', 'living.white_chair', 'living.tv_stand', 'living.end_table_cluster',
  'kitchen.island', 'kitchen.stool_1', 'kitchen.stool_2', 'kitchen.cabinet_run', 'kitchen.stove', 'kitchen.fridge', 'kitchen.pantry',
  'bath.vanity', 'bath.toilet', 'bath.shower', 'service.laundry', 'service.water_heater',
  'entry.dresser', 'closet.dresser',
]

const SECONDARY_IDS = [
  'bedroom.monitor', 'bedroom.pc', 'bedroom.projector', 'living.tv', 'living.subwoofer', 'kitchen.microwave',
]

const box = (name, x, y, w, h, zMin, zMax) => ({ kind: 'box', name, x, y, w, h, zMin, zMax })
const ellipse = (name, x, y, w, h, zMin, zMax) => ({ kind: 'ellipse', name, x, y, w, h, zMin, zMax })
const frame = (name, zMin, zMax, thickness = 0.035) => ({ kind: 'open_frame', name, zMin, zMax, thickness })

const shared = {
  xy_source: 'accepted_object_footprint',
  z_status: 'provisional_inspection',
  silhouette_status: 'provisional_inspection',
}

export const blockingProfiles = Object.freeze({
  'bedroom.bed': { recipe: 'measured_bed_23in_mattress_top_west_headboard', primitives: [box('underbed deck', .05, .06, .90, .88, 41, 52), box('mattress', .04, .04, .92, .92, 52, 78), box('west-side headboard', 0, .02, .095, .96, 0, 151), box('east-side footboard', .965, .08, .02, .84, 0, 41)] },
  'bedroom.desk_main': { recipe: 'measured_main_desktop_open_legs', primitives: [box('desktop', 0, 0, 1, 1, 96, 100), box('northwest leg', .03, .08, .04, .16, 0, 96), box('southwest leg', .03, .76, .04, .16, 0, 96), box('northeast leg', .93, .08, .04, .16, 0, 96), box('southeast leg', .93, .76, .04, .16, 0, 96)] },
  'bedroom.desk_return': { recipe: 'measured_cabinet_return_with_worktop', primitives: [box('cabinet body', .02, .02, .96, .96, 0, 96), box('worktop', 0, 0, 1, 1, 96, 101)] },
  'bedroom.chair': { recipe: 'measured_office_chair_18in_seat', primitives: [box('seat cushion', .12, .20, .76, .58, 47, 61), box('north-side backrest', .10, .05, .80, .16, 61, 137), ellipse('center pedestal', .44, .43, .12, .14, 10, 47), ellipse('caster base cue', .26, .26, .48, .48, 4, 10)] },
  'living.couch': { recipe: 'measured_sofa_east_wall_back_92x42', renderFootprint: { x: 841.34, y: 315.70, w: 142.38, h: 311.88 }, primitives: [box('lower sofa body', .06, .04, .70, .92, 0, 54.24), box('seat cushion', .05, .06, .70, .88, 54.24, 67.80), box('east-wall backrest', .74, 0, .26, 1, 54.24, 108.48), box('north arm', .04, 0, .74, .10, 54.24, 98.31), box('south arm', .04, .90, .74, .10, 54.24, 98.31)] },
  'living.coffee_table': { recipe: 'rectangular_open_frame_coffee_table', renderFootprint: { x: 715.77, y: 386.50, w: 94.92, h: 162.72 }, primitives: [
  box('tabletop', 0, 0, 1, 1, 56.0, 61.0),
  box('front left leg', 0.02, 0.02, 0.05, 0.05, 0, 56.0),
  box('front right leg', 0.93, 0.02, 0.05, 0.05, 0, 56.0),
  box('rear left leg', 0.02, 0.93, 0.05, 0.05, 0, 56.0),
  box('rear right leg', 0.93, 0.93, 0.05, 0.05, 0, 56.0),
  box('front lower rail', 0.02, 0.02, 0.96, 0.05, 0, 3.4),
  box('rear lower rail', 0.02, 0.93, 0.96, 0.05, 0, 3.4),
  box('left lower rail', 0.02, 0.02, 0.05, 0.96, 0, 3.4),
  box('right lower rail', 0.93, 0.02, 0.05, 0.96, 0, 3.4),
  box('front apron', 0.08, 0.02, 0.84, 0.035, 47.5, 50.5),
  box('rear apron', 0.08, 0.945, 0.84, 0.035, 47.5, 50.5),
  box('center support', 0.20, 0.47, 0.60, 0.06, 47.0, 49.5)
] },
  'living.white_chair': { recipe: 'homepop_round_upholstered_swivel_shell', renderFootprint: { x: 676.51, y: 247.39, w: 117.29, h: 108.14 }, primitives: [{ kind: 'ellipsoid', name: 'rounded lower upholstered shell', x: .04, y: .08, w: .92, h: .86, zMin: 0, zMax: 62 }, { kind: 'ellipsoid', name: 'rounded window-side back shell', x: .05, y: .00, w: .90, h: .62, zMin: 39, zMax: 97.29 }, { kind: 'ellipsoid', name: 'inset seat cushion', x: .18, y: .29, w: .64, h: .48, zMin: 55, zMax: 62 }] },
  'living.tv_stand': { recipe: 'measured_tv_stand_54x19x40', renderFootprint: { x: 448.33, y: 301.87, w: 64.41, h: 183.06 }, primitives: [box('cabinet mass', 0, 0, 1, 1, 0, 135.60)] },
  'living.end_table_cluster': { recipe: 'measured_end_table_20x24x24_5', renderFootprint: { x: 893.41, y: 235.70, w: 81.36, h: 67.80 }, primitives: [box('table body', 0, 0, 1, 1, 0, 83.06)] },
  'kitchen.island': { recipe: 'measured_island_78x34x36', renderFootprint: { x: 632.77, y: 771.38, w: 115.26, h: 264.42 }, primitives: [box('island base', .03, .03, .94, .94, 0, 116.96), box('countertop', 0, 0, 1, 1, 116.96, 122.04)] },
  'kitchen.stool_1': { recipe: 'four_leg_upholstered_barstool', renderFootprint: { x: 571.16, y: 823.10, w: 42.38, h: 57.63 }, primitives: [
  box('seat cushion', 0.08, 0.05, 0.84, 0.90, 81.36, 88.14),
  box('front left leg', 0.10, 0.08, 0.12, 0.12, 0, 81.36),
  box('front right leg', 0.78, 0.08, 0.12, 0.12, 0, 81.36),
  box('rear left leg', 0.10, 0.80, 0.12, 0.12, 0, 81.36),
  box('rear right leg', 0.78, 0.80, 0.12, 0.12, 0, 81.36),
  box('front stretcher', 0.18, 0.10, 0.64, 0.08, 17, 21),
  box('rear stretcher', 0.18, 0.82, 0.64, 0.08, 17, 21),
  box('left stretcher', 0.10, 0.18, 0.08, 0.64, 17, 21),
  box('right stretcher', 0.82, 0.18, 0.08, 0.64, 17, 21)
] },
  'kitchen.stool_2': { recipe: 'four_leg_upholstered_barstool', renderFootprint: { x: 571.16, y: 941.08, w: 42.38, h: 57.63 }, primitives: [
  box('seat cushion', 0.08, 0.05, 0.84, 0.90, 81.36, 88.14),
  box('front left leg', 0.10, 0.08, 0.12, 0.12, 0, 81.36),
  box('front right leg', 0.78, 0.08, 0.12, 0.12, 0, 81.36),
  box('rear left leg', 0.10, 0.80, 0.12, 0.12, 0, 81.36),
  box('rear right leg', 0.78, 0.80, 0.12, 0.12, 0, 81.36),
  box('front stretcher', 0.18, 0.10, 0.64, 0.08, 17, 21),
  box('rear stretcher', 0.18, 0.82, 0.64, 0.08, 17, 21),
  box('left stretcher', 0.10, 0.18, 0.08, 0.64, 17, 21),
  box('right stretcher', 0.82, 0.18, 0.08, 0.64, 17, 21)
] },
  'kitchen.cabinet_run': { recipe: 'entry_wall_anchored_measured_counters', renderFootprint: { x: 894.055, y: 718.52, w: 86.445, h: 528.84 }, primitives: [box('left lower cabinet', 0, 0, 1, .160256, 0, 116.96), box('left countertop', 0, 0, 1, .160256, 116.96, 122.04), box('right lower cabinet', .019608, .349359, .980392, .176282, 0, 116.96), box('right countertop', .019608, .349359, .980392, .176282, 116.96, 122.04)] },
  'kitchen.stove': { recipe: 'entry_wall_anchored_measured_range', renderFootprint: { x: 887.275, y: 803.27, w: 93.225, h: 100.005 }, primitives: [box('range body', 0, 0, 1, 1, 0, 118.65), box('cooktop', 0, 0, 1, 1, 118.65, 122.04), box('rear control backguard', .86, 0, .14, 1, 122.04, 149.16)] },
  'kitchen.fridge': { recipe: 'entry_wall_anchored_ge_fridge', renderFootprint: { x: 863.545, y: 1006.67, w: 116.955, h: 111.023 }, primitives: [box('refrigerator body', 0, 0, 1, 1, 0, 225.011)] },
  'kitchen.pantry': { recipe: 'entry_wall_anchored_tall_pantry_measured_vertical_split', renderFootprint: { x: 899.14, y: 1117.693, w: 81.36, h: 129.668 }, primitives: [box('solid bottom plinth', 0, 0, 1, 1, 0, 5.085), box('lower pantry cabinet', 0, 0, 1, 1, 5.085, 171.195), box('upper pantry cabinet', 0, 0, 1, 1, 171.195, 310.185)] },
  'bath.vanity': { recipe: 'measured_50x22_5x35_4_vanity', renderFootprint: { x: 9.76, y: 546.79, w: 76.275, h: 169.50 }, primitives: [box('vanity cabinet', .02, .01, .96, .98, 0, 116.62), box('countertop', 0, 0, 1, 1, 116.62, 120.006)] },
  'bath.toilet': { recipe: 'measured_gerber_maxwell_elongated_centered_in_36in_bay', renderFootprint: { x: 17.90, y: 747.86, w: 97.886, h: 58.901 }, primitives: [box('tank', .02, .04, .28, .92, 49, 97.039), ellipse('seat_and_bowl', .18, .06, .80, .88, 43, 57), ellipse('pedestal', .31, .18, .42, .64, 0, 43)] },
  'bath.shower': { recipe: 'measured_48_5x35x73_shower_fixed_panel_plus_door', renderFootprint: { x: 17.90, y: 855.17, w: 118.65, h: 164.415 }, primitives: [box('low shower pan', 0, 0, 1, 1, 0, 8), frame('measured enclosure frame', 8, 247.47), box('front fixed-panel divider', .965, .445, .035, .018, 8, 247.47), box('front top rail', .965, 0, .035, 1, 242, 247.47)] },
  'service.laundry': { recipe: 'measured_ge_stacked_washer_dryer', arrangement: 'dryer_above_washer', renderFootprint: { x: 310.01, y: 736.10, w: 108.48, h: 94.92 }, primitives: [box('washer', 0, 0, 1, 1, 0, 134.753), box('dryer', 0, 0, 1, 1, 134.753, 269.505)] },
  'service.water_heater': { recipe: 'measured_lowboy_plus_wall_mounted_air_handler', primitives: [ellipse('bradford_white_lowboy', .0974, .1261, .8052, .7477, 0, 116.319), box('fma4x1800al_air_handler', .02, .1950, .4807, .6101, 169.50, 293.235)] },
  'entry.dresser': { semantic_role: 'fixed_built_in_architecture', legacy_source_id: true, recipe: 'measured_entry_cubby_plus_stacked_cabinet_right_side', renderFootprint: { x: 359.64, y: 1041.315, w: 84.75, h: 208.485 }, primitives: [box('cabinet filled base', 0, 0, 1, .211382, 0, 16.95), box('cabinet lower section', 0, 0, 1, .211382, 16.95, 184.755), box('cabinet upper section', 0, 0, 1, .211382, 184.755, 283.065), box('cubby bottom shelf', 0, .211382, .76, .788618, 0, 4.5), box('cubby left side', 0, .211382, .76, .027602, 4.5, 59.3), box('cubby divider one', 0, .465317, .76, .027602, 4.5, 59.3), box('cubby divider two', 0, .718463, .76, .027602, 4.5, 59.3), box('cubby right side', 0, .972398, .76, .027602, 4.5, 59.3), box('cubby bench top', 0, .211382, .76, .788618, 59.3, 64.41)] },
  'closet.dresser': { recipe: 'measured_single_midcentury_5_drawer_chest_flush_back_and_right', renderFootprint: { x: 285.60, y: 1126.47, w: 61.02, h: 123.33 }, primitives: [box('dresser body', 0, 0, 1, 1, 10.17, 181.365), box('front-left foot', .08, .06, .12, .08, 0, 10.17), box('front-right foot', .08, .86, .12, .08, 0, 10.17), box('rear-left foot', .80, .06, .12, .08, 0, 10.17), box('rear-right foot', .80, .86, .12, .08, 0, 10.17)] },
  'bedroom.monitor': { recipe: 'thin_upright_monitor_slab', primitives: [box('upright monitor', 0, .12, 1, .76, 70, 121)] },
  'bedroom.pc': { recipe: 'under_desk_pc_tower', primitives: [box('pc tower', 0, 0, 1, 1, 0, 54)] },
  'bedroom.projector': { recipe: 'small_projector_box', primitives: [box('projector box', 0, 0, 1, 1, 82, 98)] },
  'living.tv': { recipe: 'vizio_p502ui_b1e_on_measured_tv_stand', renderFootprint: { x: 463.71, y: 318.60, w: 33.66, h: 149.60 }, primitives: [box('north tv foot', .08, .08, .84, .08, 135.60, 141.87), box('south tv foot', .08, .84, .84, .08, 135.60, 141.87), box('thin display panel', .395, 0, .21, 1, 141.87, 229.54)] },
  'living.subwoofer': { recipe: 'episode_es_sub_10_200_measured', renderFootprint: { x: 455.45, y: 241.94, w: 50.17, h: 50.17 }, primitives: [box('subwoofer cabinet', 0, 0, 1, 1, 0, 52.21)] },
  'kitchen.microwave': { recipe: 'provisional_ge_30in_over_range_measured_mount', renderFootprint: { x: 927.74, y: 803.27, w: 52.76, h: 100.01 }, primitives: [box('microwave body', 0, 0, 1, 1, 191.96, 246.62)] },
})

export const primaryBlockerIds = Object.freeze(PRIMARY_IDS)
export const secondaryBlockerIds = Object.freeze(SECONDARY_IDS)

function boundedPrimitive(primitive) {
  const values = [primitive.x ?? 0, primitive.y ?? 0, primitive.w ?? 1, primitive.h ?? 1]
  return values.every(Number.isFinite) && primitive.x >= 0 && primitive.y >= 0
    && primitive.w >= 0 && primitive.h >= 0 && primitive.x + primitive.w <= 1 && primitive.y + primitive.h <= 1
}

export function buildBlockingProfiles(objects) {
  const byId = new Map(objects.map((object) => [object.id, object]))
  const ids = [...PRIMARY_IDS, ...SECONDARY_IDS]
  if (ids.some((id) => !byId.has(id))) throw new Error(`Missing accepted object footprint(s): ${ids.filter((id) => !byId.has(id)).join(', ')}`)
  return ids.map((id) => {
    const source = byId.get(id)
    const profile = blockingProfiles[id]
    if (!profile || profile.primitives.some((primitive) => primitive.kind !== 'open_frame' && !boundedPrimitive(primitive))) {
      throw new Error(`Blocker profile ${id} escapes its accepted source footprint`)
    }
    return {
      ...shared,
      ...profile,
      id,
      scope: PRIMARY_IDS.includes(id) ? 'primary' : 'secondary',
      sourceFootprint: source.rect,
      sourceLabel: source.label,
      source: source.source,
    }
  })
}
