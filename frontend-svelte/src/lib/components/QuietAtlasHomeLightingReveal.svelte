<script>
  import QuietAtlasRoomControls from './QuietAtlasRoomControls.svelte'

  export let id
  export let group
  export let open = false
  // Preserve the caller's existing binding without allowing preview drafts
  // to affect actual light states or send commands.
  export let drafts = {}
</script>

<div class="reveal" class:open {id} hidden={!open}>
  {#if open}
    <section class="shelf" aria-labelledby={`${id}-title`}>
      <div class="introduction">
        <p class="eyebrow">ROOM LIGHTING</p>
        <h3 id={`${id}-title`}>{group.name}</h3>
        <p class="explanation">Adjust individual lights right here, without leaving Home. These are the same functional controls available on the original Apartment page.</p>
      </div>
      <QuietAtlasRoomControls room={group.id} id={`${id}-fixtures`} />
    </section>
  {/if}
</div>

<style>
  .reveal {min-width:0;}
  .reveal[hidden] {display:none;}
  .shelf {box-sizing:border-box;min-width:0;padding:28px;margin:10px 0 16px;border:1px solid var(--line);border-radius:16px;background:var(--deep);color:var(--ink);animation:unfold 220ms ease-out;}
  .introduction {margin-bottom:22px;}
  .eyebrow {font-size:12px;letter-spacing:.13em;color:var(--gold);margin:0 0 12px;}
  h3 {font-size:clamp(22px,2.4vw,30px);font-weight:550;line-height:1.2;margin:0 0 10px;}
  .explanation {font-size:14px;line-height:1.6;color:var(--muted);max-width:60ch;margin:0;}
  @keyframes unfold {from {opacity:0;transform:translateY(-6px);} to {opacity:1;transform:translateY(0);}}
  @media (max-width:700px) {.shelf {padding:20px 16px;margin:0 0 5px;border-radius:10px 10px 16px 16px;}.introduction{margin-bottom:14px;}h3{font-size:25px;}}
  @media (prefers-reduced-motion:reduce) {.shelf {animation:none;}}
</style>
