<script>
  // Root layout — full-bleed canvas, no chrome.
</script>

<slot />

<style>
  :global(html, body) {
    margin: 0;
    padding: 0;
    height: 100%;
    background: #000;
    overflow: hidden;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    color: #e8e9ed;
  }
</style>
