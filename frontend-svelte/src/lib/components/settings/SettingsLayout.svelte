<script>
  /** @typedef {{id: string, label: string, icon?: any}} SectionDef */

  /** @type {SectionDef[]} */
  export let sections = []
  /** @type {string} */
  export let activeId = ''
  /** @type {(id: string) => void} */
  export let onSelect = () => {}

  import SettingsRail from './SettingsRail.svelte'
</script>

<div class="settings-shell">
  <SettingsRail {sections} {activeId} {onSelect} />
  <article class="settings-main">
    <slot />
  </article>
</div>

<style>
  .settings-shell {
    display: grid;
    grid-template-columns: 260px 1fr;
    gap: 24px;
    min-height: calc(100vh - 200px);
    align-items: start;
  }

  .settings-main {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 20px;
    animation: settingsMainFade 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) both;
  }

  @keyframes settingsMainFade {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
  }

  @media (max-width: 900px) {
    .settings-shell {
      grid-template-columns: 1fr;
    }
  }
</style>
