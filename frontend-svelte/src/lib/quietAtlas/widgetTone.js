/** Presentation-only accents, never automation inputs or a weather forecast. */
export function weatherTone(view) {
  if (view?.status !== 'recent' || !view.report || typeof view.report.description !== 'string') return 'neutral'
  const description = view.report.description.toLowerCase()
  if (/thunder|lightning|storm/.test(description)) return 'storm'
  if (/snow|sleet|freezing|ice|flurr/.test(description)) return 'snow'
  if (/rain|drizzle|shower/.test(description)) return 'rain'
  if (/cloud|overcast|fog|mist|haze|smoke/.test(description)) return 'cloud'
  if (/sunny|sunshine/.test(description)) return 'sun'
  if (/clear|fair/.test(description)) return 'clear'
  return 'neutral'
}

/** Use the existing validated display labels; never infer an activity. */
export function activityTone(label) {
  switch (label) {
    case 'Working': return 'focus'
    case 'Gaming': return 'play'
    case 'Watching': return 'cinema'
    case 'Cooking': return 'warm'
    case 'Relaxing': return 'calm'
    case 'Social': return 'social'
    default: return 'neutral'
  }
}

/** Validated provider icon, including its reported day/night distinction.
 * Keep an unknown or missing icon neutral with a condition-only fallback.
 * @param {unknown} icon
 */
export function weatherIconCode(icon) {
  return typeof icon === 'string' && /^(01|02|03|04|09|10|11|13|50)[dn]$/.test(icon) ? icon : null
}

/** @param {{status:string,report?:{description:string,icon?:string|null}|null}|null} view */
export function weatherSky(view) {
  if (view?.status !== 'recent' || !view.report) return 'neutral'
  const icon = weatherIconCode(view.report.icon)
  switch (icon) {
    case '01d': return 'sun'
    case '01n': return 'night'
    case '02d': return 'partly-day'
    case '02n': return 'partly-night'
    case '03d': case '04d': return 'cloud'
    case '03n': case '04n': return 'cloud-night'
    case '09d': case '10d': return 'rain'
    case '09n': case '10n': return 'rain-night'
    case '11d': case '11n': return 'storm'
    case '13d': case '13n': return 'snow'
    case '50d': case '50n': return 'mist'
    default: return weatherTone(view)
  }
}
