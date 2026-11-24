<script>
  import { onMount } from 'svelte'
  let password = ''
  let authenticated = false
  let checking = true
  let confirmLock = false
  let open = false
  let busy = false
  let error = ''

  onMount(async () => {
    try {
      const response = await fetch('/api/owner/session', { credentials: 'same-origin', cache: 'no-store' })
      authenticated = (await response.json()).authenticated === true
    } catch { /* Read-only state remains available. */ }
    finally { checking = false }
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
    if (!authenticated || !confirmLock || busy) return
    busy = true
    error = ''
    try {
      const response = await fetch('/api/owner/session', { method: 'DELETE', credentials: 'same-origin' })
      if (!response.ok) throw new Error('logout failed')
      window.location.reload()
    } catch { error = 'Unable to lock this session.'; busy = false }
  }
</script>

<section class="owner-unlock" aria-label="Owner device access">
  <div class="access-heading">
    <strong>Owner access</strong>
    <small>{checking ? 'Checking this device…' : authenticated ? 'This device is trusted' : 'Unlock to use protected controls'}</small>
  </div>
  {#if !checking && authenticated}
    {#if confirmLock}
      <p class="lock-note">Locking signs out this browser. It does not change the house mode.</p>
      <div class="access-actions">
        <button type="button" on:click={() => confirmLock = false} disabled={busy}>Cancel</button>
        <button type="button" on:click={lock} disabled={busy}>Confirm lock</button>
      </div>
    {:else}
      <button type="button" on:click={() => confirmLock = true} disabled={busy}>Lock this device</button>
    {/if}
  {:else if !checking}
    <button type="button" on:click={() => open = !open} aria-expanded={open} aria-controls="owner-login">Unlock owner controls</button>
    {#if open}
      <form id="owner-login" on:submit|preventDefault={unlock}>
        <label for="owner-password">Owner passphrase</label>
        <input id="owner-password" type="password" autocomplete="current-password" bind:value={password} required maxlength="1024" />
        <button type="submit" disabled={busy}>Unlock</button>
      </form>
    {/if}
  {/if}
  {#if error}<p role="alert">{error}</p>{/if}
</section>

<style>
  .owner-unlock {display:grid;gap:10px;padding:14px;border:1px solid rgba(190,215,188,.24);border-radius:14px;background:#18271f;color:#edf1e7;min-width:0;box-sizing:border-box;}
  .access-heading {display:grid;gap:4px;}
  .access-heading strong {font-size:14px;font-weight:700;}
  .access-heading small,.lock-note {font-size:12px;color:#b9cbbd;line-height:1.5;}
  .access-actions {display:flex;flex-wrap:wrap;gap:8px;}
  .access-actions button {flex:1 1 95px;}
  form {display:grid;gap:8px;}
  form label {font-size:13px;}
  button, input { font: inherit; min-height: 44px; box-sizing: border-box; }
  button {padding:9px 12px;border-radius:10px;border:1px solid #536d59;background:#25392b;color:#edf1e7;font-size:13px;cursor:pointer;}
  input {min-width:0;width:100%;padding:8px 10px;border-radius:9px;border:1px solid #65816d;background:#101c15;color:#fff;}
  button:disabled {opacity:.55;cursor:not-allowed;}
  button:focus-visible, input:focus-visible { outline: 2px solid white; outline-offset: 2px; }
  p {margin:0;max-width:32ch;font-size:13px;}
</style>
