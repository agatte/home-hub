<script>
  // Legend reduced to the diagram hint only — primary mode + confidence
  // are already shown in the ModeOverlay header and the nucleus core.
</script>

<div class="legend">
  <span>inner · voters</span>
  <span class="sep">·</span>
  <span>outer · context</span>
</div>

<style>
  .legend {
    position: absolute;
    bottom: 10px;
    right: 16px;
    display: flex;
    gap: 6px;
    align-items: center;
    font-family: 'Source Sans 3', sans-serif;
    font-size: 10.5px;
    color: rgba(255, 255, 255, 0.3);
    letter-spacing: 0.2px;
    pointer-events: none;
    user-select: none;
  }
  .sep {
    opacity: 0.6;
  }
</style>
