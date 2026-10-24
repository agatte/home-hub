/**
 * Read-only snapshot provenance for the Quiet Atlas review route (#270).
 * A recent API response is not fixture telemetry recency or write permission.
 */
export const DEFAULT_SNAPSHOT_MAX_AGE_MS = 30_000;

/** @typedef {{connected:boolean,generation:number,requestId:number,pending:boolean,receivedAt:number|null,fixtures:Record<string,object>}} ReadOnlySnapshot */

/** @returns {ReadOnlySnapshot} */
export function newReadOnlySnapshot() {
  return {connected:false,generation:0,requestId:0,pending:false,receivedAt:null,fixtures:{}};
}
/** @param {ReadOnlySnapshot} state @param {boolean} connected @returns {ReadOnlySnapshot} */
export function connectionChanged(state,connected) {
  if (state.connected === connected) return state;
  return {...state,connected,generation:state.generation+1,pending:false,receivedAt:null};
}
/** Invalidate pending reads after a tab suspension, even if WS stayed open.
 * @param {ReadOnlySnapshot} state @returns {ReadOnlySnapshot}
 */
export function invalidateLightRead(state) {
  return {...state,generation:state.generation+1,pending:false,receivedAt:null};
}
/** @param {ReadOnlySnapshot} state
 * @returns {{state:ReadOnlySnapshot,ticket:{generation:number,requestId:number}|null}}
 */
export function beginLightRead(state) {
  if (!state.connected) return {state,ticket:null};
  const requestId=state.requestId+1;
  return {state:{...state,requestId,pending:true},ticket:{generation:state.generation,requestId}};
}
/** @param {ReadOnlySnapshot} state @param {{generation:number,requestId:number}|null} ticket */
function isCurrent(state,ticket) {
  return Boolean(state.connected && state.pending && ticket &&
    state.generation===ticket.generation && state.requestId===ticket.requestId);
}
/** @param {unknown} rows @returns {Record<string,object>|null} */
function validateLightList(rows) {
  if (!Array.isArray(rows)) return null;
  /** @type {Record<string,object>} */
  const map=Object.create(null);
  for (const row of rows) {
    if (!row || typeof row!=='object' || Array.isArray(row)) return null;
    const id=row.light_id;
    if (typeof id!=='string' || !id.trim() || id!==id.trim() ||
        Object.hasOwn(map,id) || id==='__proto__') return null;
    map[id]={...row};
  }
  return map;
}
/** @param {ReadOnlySnapshot} state @param {{generation:number,requestId:number}|null} ticket
 * @param {unknown} rows @param {number} receivedAtMs @returns {ReadOnlySnapshot}
 */
export function acceptLightRead(state,ticket,rows,receivedAtMs) {
  if (!isCurrent(state,ticket)) return state;
  const fixtures=validateLightList(rows);
  if (!fixtures || !Number.isFinite(receivedAtMs) || receivedAtMs<0) {
    return {...state,pending:false,receivedAt:null};
  }
  return {...state,pending:false,receivedAt:receivedAtMs,fixtures};
}
/** @param {ReadOnlySnapshot} state @param {{generation:number,requestId:number}|null} ticket @returns {ReadOnlySnapshot} */
export function failLightRead(state,ticket) {
  return isCurrent(state,ticket) ? {...state,pending:false,receivedAt:null} : state;
}
/** @param {ReadOnlySnapshot} state @param {number} nowMs
 * @param {number} [maxAgeMs]
 * @returns {'disconnected'|'unverified'|'recent-read'|'stale-read'}
 */
export function readStatus(state,nowMs,maxAgeMs=DEFAULT_SNAPSHOT_MAX_AGE_MS) {
  if (!state.connected) return 'disconnected';
  if (state.receivedAt===null) return 'unverified';
  if (!Number.isFinite(nowMs)||!Number.isFinite(maxAgeMs)||maxAgeMs<=0||
      nowMs<state.receivedAt||nowMs-state.receivedAt>maxAgeMs) return 'stale-read';
  return 'recent-read';
}
/** This display-only module never grants device write permission. */
export function permitsDeviceWrite() {return false;}
