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
