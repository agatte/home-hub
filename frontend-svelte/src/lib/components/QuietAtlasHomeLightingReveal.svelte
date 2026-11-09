<script>
  export let id
  export let group
  export let open = false
  // Shared between phone and dock; illustrative values never represent devices.
  export let drafts = {}
  const moods = ['Gentle', 'Balanced', 'Brighter']
  $: draft = drafts[group.id] ?? { mood: 'Gentle', brightness: 40, on: true }
  function update(patch) {
    drafts = { ...drafts, [group.id]: { ...draft, ...patch } }
  }
</script>

<div class="reveal" class:open {id} hidden={!open}>
  {#if open}
    <section class="shelf" aria-labelledby={`${id}-title`} aria-describedby={`${id}-notice`} style={`--preview-strength:${draft.on ? draft.brightness / 100 : 0};--preview-hue:${draft.mood === 'Gentle' ? 38 : draft.mood === 'Balanced' ? 65 : 110}`}>
      <div class="introduction">
        <p class="eyebrow">ATMOSPHERE / LOCAL STUDY</p>
        <h3 id={`${id}-title`}>{group.name}, in a different light.</h3>
        <p id={`${id}-notice`} class="notice">Design preview only — no light changes</p>
        <p class="explanation">An idea for the room, not a device reading. These choices only change this illustration.</p>
      </div>
      <div class="preview-controls">
        <div class="power-row">
          <span>Preview power</span>
          <button type="button" aria-pressed={draft.on} on:click={() => update({ on: !draft.on })}>
            {draft.on ? 'Preview on' : 'Preview off'}
          </button>
        </div>
        <fieldset>
          <legend>Illustrative lighting mood</legend>
          <div class="moods">
            {#each moods as mood}
              <button type="button" aria-pressed={draft.mood === mood} on:click={() => update({ mood })}>{mood}</button>
            {/each}
          </div>
        </fieldset>
        <label for={`${id}-brightness`}>Preview glow <span>{draft.brightness}% · local draft</span></label>
        <input id={`${id}-brightness`} type="range" min="10" max="100" step="5" value={draft.brightness} on:input={(event) => update({ brightness: Number(event.currentTarget.value) })} />
        <div class="rail-labels" aria-hidden="true"><span>Soft edge</span><span>More radiance</span></div>
        <a href="/quiet-atlas/control">Control · precision workspace <span aria-hidden="true">↗</span></a>
      </div>
    </section>
  {/if}
</div>

<style>
  .reveal {min-width:0;}
  .reveal[hidden] {display:none;}
  .shelf {position:relative;isolation:isolate;overflow:hidden;box-sizing:border-box;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:36px;padding:30px;margin:10px 0 16px;border:1px solid var(--line);border-radius:16px;background:var(--deep);color:var(--ink);animation:unfold 220ms ease-out;}
  .shelf::before {content:'';position:absolute;z-index:-1;inset:0;pointer-events:none;opacity:var(--preview-strength);background:radial-gradient(ellipse at 8% 35%,hsl(var(--preview-hue) 65% 70% / .35),transparent 68%);transition:opacity 180ms ease;}
  .eyebrow {font-size:12px;letter-spacing:.13em;color:var(--gold);margin:0 0 14px;}
  h3 {font-size:clamp(22px,2.4vw,30px);font-weight:550;letter-spacing:-.035em;line-height:1.2;margin:0 0 20px;}
  .notice {font-size:14px;font-weight:650;line-height:1.5;margin:0 0 8px;}
  .explanation {font-size:14px;line-height:1.6;color:var(--muted);max-width:38ch;margin:0;}
  .preview-controls {min-width:0;}
  .power-row {display:flex;align-items:center;justify-content:space-between;gap:12px;border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:17px;font-size:14px;}
  .power-row button {flex:0 0 auto;min-width:116px;}
  fieldset {min-width:0;border:0;margin:0 0 22px;padding:0;}
  legend,label {font-size:14px;margin-bottom:10px;}
  .moods {display:flex;flex-wrap:wrap;gap:6px;}
  button {flex:1;min-height:44px;padding:8px 10px;border:1px solid var(--line);border-radius:100px;background:transparent;color:var(--ink);font:inherit;font-size:14px;cursor:pointer;}
  button[aria-pressed="true"] {border-color:var(--gold);background:var(--stage);box-shadow:inset 0 0 0 1px var(--gold);}
  label {display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;}
  label span,.rail-labels {color:var(--muted);font-size:13px;}
  input {width:100%;min-width:0;min-height:44px;margin:0;accent-color:var(--gold);cursor:pointer;}
  .rail-labels {display:flex;justify-content:space-between;gap:8px;}
  a {display:inline-flex;align-items:center;gap:12px;min-height:44px;margin-top:14px;color:var(--gold);font-size:14px;text-decoration:underline;text-underline-offset:4px;}
  button:focus-visible,input:focus-visible,a:focus-visible {outline:3px solid var(--gold);outline-offset:3px;}
  @keyframes unfold {from {opacity:0;transform:translateY(-6px);} to {opacity:1;transform:translateY(0);}}
  @media (max-width:700px) {.shelf {grid-template-columns:minmax(0,1fr);gap:24px;padding:24px 18px;margin:0 0 5px;border-radius:10px 10px 16px 16px;} h3 {font-size:25px;} .explanation {max-width:none;}}
  @media (prefers-reduced-motion:reduce) {.shelf {animation:none;} .shelf::before {transition:none;}}
</style>
