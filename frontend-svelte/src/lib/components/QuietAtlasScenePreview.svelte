<script>
  /** @type {ReturnType<typeof import('$lib/quietAtlas/scenePreview.js').scenePreviewRows>} */
  export let rows = []
  export let title = 'Apartment preview'
  const rooms = ['Bedroom', 'Living room', 'Kitchen']
</script>

<div class="scene-preview" aria-label={title}>
  <div class="preview-heading"><strong>{title}</strong><span>On-screen only</span></div>
  <div class="apartment">
    {#each rooms as room}
      <div class="room" class:kitchen={room === 'Kitchen'}>
        <span class="room-name">{room}</span>
        <div class="fixtures">
          {#each rows.filter(row => row.room === room) as fixture (fixture.id)}
            <div class="fixture" class:unlit={fixture.power !== 'On'} data-fixture={fixture.id}>
              <span class="glow" class:unknown={fixture.power === 'Not specified'} style:--glow={fixture.color ?? '#9ca3a0'} style:--strength={fixture.power === 'On' && fixture.brightness !== null && fixture.color ? fixture.brightness / 100 : 0}>
                <span></span>
              </span>
              <strong>{fixture.name}</strong>
              <small>{fixture.power}{fixture.power === 'On' ? ' · ' + (fixture.brightness === null ? 'Brightness unspecified' : fixture.brightness + '%') : ''}</small>
              {#if fixture.power === 'On'}<small>{fixture.colorLabel}</small>{/if}
            </div>
          {/each}
        </div>
      </div>
    {/each}
  </div>
  <p>Approximate declared colors and brightness, not a measured light state. Unspecified fixtures are not assumed off. Effects and room lighting interactions are not simulated.</p>
</div>

<style>
  .scene-preview{margin:10px 0 16px;min-width:0;}
  .preview-heading{display:flex;flex-wrap:wrap;justify-content:space-between;gap:6px;align-items:center;margin-bottom:10px;color:var(--hh-ink,#f1eee7);font-size:14px;}
  .preview-heading span,.scene-preview p{color:var(--hh-muted,#bec8c0);font-size:12px;line-height:1.5;}
  .apartment{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:2px;border:1px solid var(--hh-line,#4a5b50);border-radius:14px;overflow:hidden;background:#36443c;}
  .room{min-width:0;padding:12px 8px;background:#1a2420;}
  .room.kitchen{grid-column:1/-1;}
  .room-name{display:block;text-align:center;color:#cad5ca;font-size:11px;letter-spacing:.08em;text-transform:uppercase;}
  .fixtures{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;}
  .fixture{display:flex;flex-direction:column;align-items:center;text-align:center;gap:4px;min-width:0;overflow-wrap:anywhere;}
  .glow{position:relative;display:grid;place-items:center;width:44px;height:44px;margin:4px auto 0;border-radius:50%;background:radial-gradient(circle,color-mix(in srgb,var(--glow) calc(var(--strength)*75%),transparent),transparent 70%);}
  .glow span{width:13px;height:13px;border:1px solid #b0b8ae;border-radius:50%;background:var(--glow);}
  .unlit .glow span{background:#35413c;border-color:#68756e;}
  .glow.unknown span{background:transparent;border-style:dashed;}
  .fixture strong{font-size:12px;color:#e8eee6;}
  .fixture small{font-size:10px;color:#c1cbc1;line-height:1.4;}
  .scene-preview p{margin:9px 0 0;}
  @media(max-width:380px){.room{padding:10px 5px}.fixtures{gap:4px}}
</style>
