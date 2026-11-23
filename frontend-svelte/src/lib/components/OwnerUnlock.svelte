<script>
  import { onMount } from 'svelte'
  let password = ''
  let authenticated = false
  let open = false
  let busy = false
  let error = ''

  onMount(async () => {
    try {
      const response = await fetch('/api/owner/session', { credentials: 'same-origin', cache: 'no-store' })
      authenticated = (await response.json()).authenticated === true
    } catch { /* Read-only state remains available. */ }
  })

  async function unlock() {
    if (busy) return
    busy = true
    error = ''
    const secret = password
    password = ''
    try {
      const response = await fetch('/api/owner/session', {
        method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: secret })
      })
      if (!response.ok) {
        error = response.status === 429 ? 'Too many attempts. Try again later.' : 'Unable to unlock. Check credentials and connection security.'
        return
      }
      window.location.reload()
    } catch {
      error = 'Unable to reach owner login.'
    } finally { busy = false }
  }

  async function lock() {
    busy = true
    try {
      const response = await fetch('/api/owner/session', { method: 'DELETE', credentials: 'same-origin' })
      if (!response.ok) throw new Error('logout failed')
      window.location.reload()
    } catch { error = 'Unable to lock this session.'; busy = false }
  }
</script>

<div class="owner-unlock">
  {#if authenticated}
    <button type="button" on:click={lock} disabled={busy} aria-label="Lock owner controls"><span class="full-label">Lock owner controls</span><span class="compact-label" aria-hidden="true">Lock</span></button>
  {:else}
    <button type="button" on:click={() => open = !open} aria-expanded={open} aria-controls="owner-login" aria-label="Unlock owner controls"><span class="full-label">Unlock owner controls</span><span class="compact-label" aria-hidden="true">Unlock</span></button>
    {#if open}
      <form id="owner-login" on:submit|preventDefault={unlock}>
        <label for="owner-password">Owner passphrase</label>
        <input id="owner-password" type="password" autocomplete="current-password" bind:value={password} required maxlength="1024" />
        <button type="submit" disabled={busy}>Unlock</button>
      </form>
    {/if}
  {/if}
  {#if error}<p role="alert">{error}</p>{/if}
</div>

<style>
  .owner-unlock { position: fixed; right: 1rem; top: 1rem; z-index: 100; padding: .5rem; border-radius: .5rem; background: #20252d; color: white; }
  form { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; padding-top: .5rem; }
  button, input { font: inherit; min-height: 44px; box-sizing: border-box; }
  button { padding: .625rem .75rem; border-radius: .375rem; }
  input { min-width: 0; flex: 1 1 12rem; padding: .5rem .625rem; }
  button:focus-visible, input:focus-visible { outline: 2px solid white; outline-offset: 2px; }
  p { max-width: 24rem; }
  .compact-label { display:none; }
  @media (max-width:760px) {
    /* Keep the owner gate reachable without covering HomeHub's phone header. */
    .owner-unlock {right:10px;top:11px;padding:0;max-width:calc(100vw - 20px);border:1px solid rgba(190,215,188,.2);box-shadow:0 6px 20px rgba(0,0,0,.2);}
    .owner-unlock > button {min-height:44px;padding:8px 12px;font-size:12px;font-weight:650;}
    .full-label {display:none;}
    .compact-label {display:inline;}
    .owner-unlock:has(form) {width:min(330px,calc(100vw - 20px));padding:12px;box-sizing:border-box;}
    form {flex-direction:column;align-items:stretch;gap:9px;}
    input {width:100%;min-width:0;flex-basis:auto;}
  }
</style>
