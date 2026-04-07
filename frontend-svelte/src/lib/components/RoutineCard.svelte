<script>
  import { onMount } from 'svelte'
  import { apiGet, apiPost } from '$lib/api.js'

  /** @type {any[]} */
  let routines = []
  let testing = false

  onMount(async () => {
    try {
      const data = await apiGet('/api/routines')
      routines = data.routines || []
    } catch {
      /* ignore */
    }
  })

  $: morningRoutine = routines.find((r) => r.name === 'morning_routine')

  async function testMorning() {
    testing = true
    try {
      await apiPost('/api/routines/morning/test')
    } catch {
      /* ignore */
    }
    testing = false
  }

  async function toggleMorning() {
    try {
      const data = await apiPost('/api/routines/morning/toggle')
      routines = routines.map((r) =>
        r.name === 'morning_routine' ? { ...r, enabled: data.enabled } : r
      )
    } catch {
      /* ignore */
    }
  }
</script>

{#if morningRoutine}
  <div class="routine-card">
    <div class="routine-header">
      <div class="routine-info">
        <span class="routine-icon">☀️</span>
        <div>
          <span class="routine-name">Morning Routine</span>
          <span class="routine-time">{morningRoutine.time} · Mon–Fri</span>
        </div>
      </div>
      <div class="routine-actions">
        <button
          class="routine-toggle"
          class:routine-enabled={morningRoutine.enabled}
          on:click={toggleMorning}
        >
          {morningRoutine.enabled ? 'ON' : 'OFF'}
        </button>
        <button class="routine-test-btn" on:click={testMorning} disabled={testing}>
          {testing ? 'Running...' : 'Test'}
        </button>
      </div>
    </div>
    {#if morningRoutine.next_run && morningRoutine.enabled}
      <div class="routine-next">
        Next: {new Date(morningRoutine.next_run).toLocaleString()}
      </div>
    {/if}
  </div>
{/if}
