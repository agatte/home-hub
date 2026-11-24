// Match the existing guarded brightness route's whole-target contract.
// No client-side light authority is inferred from validation.
/** @param {any} row */
export function validBrightnessSuggestion(row) {
  if (!row || row.kind !== 'brightness' || !Number.isSafeInteger(row.id) || row.id <= 0 ||
      !Number.isInteger(row.confidence) || row.confidence < 0 || row.confidence > 100 ||
      !Number.isSafeInteger(row.sample_count) || row.sample_count <= 0) return false
  const p = row.payload
  if (!p || typeof p !== 'object' || Array.isArray(p) ||
      !['mode','period','weather_class'].every(k => typeof p[k] === 'string' && p[k].trim())) return false
  const raw = p.light_targets ?? (['string','number'].includes(typeof p.light_id) ? {[String(p.light_id)]:p.suggested_bri} : null)
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return false
  const targets = Object.entries(raw)
  return targets.length > 0 && targets.every(([id,bri]) => ['1','2','3','4','5','6'].includes(id) && typeof bri === 'number' && Number.isInteger(bri) && bri >= 1 && bri <= 254)
}

/** @param {any} row */
export function validModeSuggestion(row) {
  return !!row && Number.isSafeInteger(row.suggestion_id) && row.suggestion_id > 0 &&
    Number.isSafeInteger(row.rule_id) && row.rule_id > 0 &&
    ['relax','working','watching','gaming','cooking','social'].includes(row.predicted_mode) &&
    Number.isInteger(row.confidence) && row.confidence >= 0 && row.confidence <= 100 &&
    Number.isSafeInteger(row.sample_count) && row.sample_count > 0
}
