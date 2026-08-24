export const SYNTHETIC_PREVIEW_STATES = Object.freeze({
  rest: Object.freeze({
    id: 'rest',
    label: 'Rest',
    activeZone: null,
    lamps: Object.freeze({ bedroomL2: false, bedroomL5: false }),
    displays: Object.freeze({ monitor: false, tv: false }),
    alexa: 'dormant',
  }),
  desk: Object.freeze({
    id: 'desk',
    label: 'Desk active',
    activeZone: 'bedroom.desk',
    lamps: Object.freeze({ bedroomL2: true, bedroomL5: true }),
    displays: Object.freeze({ monitor: true, tv: false }),
    alexa: 'dormant',
  }),
})

export const DEFAULT_SYNTHETIC_PREVIEW_STATE = 'rest'

export function resolveSyntheticPreviewState(search = '') {
  const params = search instanceof URLSearchParams
    ? search
    : new URLSearchParams(String(search).replace(/^\?/, ''))
  const requested = params.get('state') ?? DEFAULT_SYNTHETIC_PREVIEW_STATE
  return SYNTHETIC_PREVIEW_STATES[requested] ?? SYNTHETIC_PREVIEW_STATES[DEFAULT_SYNTHETIC_PREVIEW_STATE]
}
