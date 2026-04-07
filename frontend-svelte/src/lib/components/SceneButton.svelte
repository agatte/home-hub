<script>
  export let name = ''
  export let displayName = ''
  /** @type {(name: string) => void} */
  export let onActivate = () => {}

  /** @type {Record<string, string>} */
  const SCENE_ICONS = {
    movie_night: '🎬',
    bright: '☀️',
    colts_blue: '🏈',
    relax: '🌙',
    all_off: '⏻',
    warm_white: '💡',
    daylight: '🌤',
  }
</script>

<button class="scene-btn" on:click={() => onActivate(name)}>
  <span class="scene-icon">{SCENE_ICONS[name] || '💡'}</span>
  <span class="scene-name">{displayName}</span>
</button>
