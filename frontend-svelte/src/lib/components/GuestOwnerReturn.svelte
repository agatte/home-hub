<script>
  import { onMount } from 'svelte'
  import { ChevronLeft } from 'lucide-svelte'

  let authenticated = false

  // Informational status only. The public guest gateway does not forward
  // this endpoint. A missing, invalid or unavailable response hides the link.
  // Navigation never grants or revokes a session.
  onMount(() => {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 5000)
    async function checkOwner() {
      try {
        const response = await fetch('/api/owner/session', {
          credentials: 'same-origin',
          cache: 'no-store',
          redirect: 'error',
          signal: controller.signal,
        })
        if (!response.ok || controller.signal.aborted) return
        const result = await response.json()
        if (!controller.signal.aborted) authenticated = result?.authenticated === true
      } catch {
        // Guest visitors and unavailable sessions have no owner return link.
      } finally {
        clearTimeout(timeout)
      }
    }
    checkOwner()
    return () => {
      clearTimeout(timeout)
      controller.abort()
    }
  })
</script>

{#if authenticated}
  <div class="owner-return">
    <a href="/" data-sveltekit-reload aria-label="Return to HomeHub">
      <ChevronLeft size={21} strokeWidth={2} aria-hidden="true" />
      Return to HomeHub
    </a>
    <span>Guest preview</span>
  </div>
{/if}

<style>
  .owner-return {position:sticky;top:0;z-index:40;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:8px 10px;margin:0 0 22px;border:1px solid rgba(245,243,238,.15);border-radius:14px;background:#26312b;}
  a {display:inline-flex;align-items:center;gap:4px;min-height:44px;color:#f5f3ee;text-decoration:none;font-size:14px;font-weight:650;}
  a:focus-visible {outline:3px solid #e4d2a7;outline-offset:3px;border-radius:6px;}
  span {color:#c3c9bd;font-size:11px;line-height:1.4;text-align:right;}
</style>
