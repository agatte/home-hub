/**
 * Interpret the guarded brightness receipt, not the HTTP status or a physical
 * state estimate. Missing/legacy/malformed receipts remain unconfirmed.
 * @param {unknown} value
 * @returns {{message:string,incomplete:boolean}}
 */
export function brightnessAcceptanceFeedback(value) {
  const unknown = {message:'Brightness acceptance unconfirmed. Check saved preferences and actual lights before another action.',incomplete:true}
  if (!value || typeof value !== 'object') return unknown
  const r = /** @type {Record<string, any>} */ (value)
  if (!['ok','partial_failure'].includes(r.status)) return unknown
  const keys = ['preference_saved','preference_uncertain','preference_not_attempted','blocked','unavailable','uncertain','not_attempted']
  if (!keys.every(k => Array.isArray(r[k]) && r[k].every(id => typeof id === 'string' && id.length > 0) && new Set(r[k]).size === r[k].length)) return unknown
  if (!Array.isArray(r.applied_now) || !r.applied_now.every(row => row && typeof row.light_id === 'string' && Number.isInteger(row.bri) && row.bri >= 1 && row.bri <= 254)) return unknown
  const pref = [...r.preference_saved,...r.preference_uncertain,...r.preference_not_attempted]
  const physical = [...r.applied_now.map(row => row.light_id),...r.blocked,...r.unavailable,...r.uncertain,...r.not_attempted]
  if (!pref.length || new Set(pref).size !== pref.length || new Set(physical).size !== physical.length || physical.length !== pref.length || !physical.every(id => pref.includes(id))) return unknown
  const incomplete = keys.slice(1).some(k => r[k].length > 0)
  if ((r.status === 'ok') === incomplete) return unknown
  const preference = `Preferences: ${r.preference_saved.length} saved, ${r.preference_uncertain.length} uncertain, ${r.preference_not_attempted.length} not attempted.`
  const lights = `Immediate requests: ${r.applied_now.length} acknowledged, ${r.blocked.length} blocked, ${r.unavailable.length} unavailable, ${r.uncertain.length} uncertain, ${r.not_attempted.length} not attempted.`
  return {message: preference + ' ' + lights + ' Check actual lights' + (incomplete ? ' and saved preferences before another action.' : '; acknowledgement is not physical confirmation.'), incomplete}
}
