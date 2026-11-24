<script>
  import QuietAtlasRoomControls from './QuietAtlasRoomControls.svelte'

  export let id
  export let group
  export let open = false
</script>

<div class="reveal" class:open {id} hidden={!open}>
  {#if open}
    <section class="shelf" aria-labelledby={`${id}-title`}>
      <div class="introduction">
        <h3 id={`${id}-title`}>{group.name} lights</h3>
      </div>
      <QuietAtlasRoomControls room={group.id} id={`${id}-fixtures`} compact={true} />
    </section>
  {/if}
</div>

<style>
  .reveal {min-width:0;}
  .reveal[hidden] {display:none;}
  .shelf {box-sizing:border-box;min-width:0;padding:18px 20px 10px;margin:8px 0 12px;border:1px solid var(--line);border-top:2px solid var(--gold);border-radius:15px;background:linear-gradient(130deg,var(--stage),var(--deep));color:var(--ink);animation:unfold 220ms ease-out;}
  .introduction {margin-bottom:10px;}
  h3 {font-size:18px;font-weight:650;line-height:1.3;letter-spacing:-.025em;margin:0;}
  @keyframes unfold {from {opacity:0;transform:translateY(-6px);} to {opacity:1;transform:translateY(0);}}
  @media (max-width:700px) {.shelf {padding:14px 12px 6px;margin:0 0 4px;}.introduction{margin-bottom:8px;}}
  @media (prefers-reduced-motion:reduce) {.shelf {animation:none;}}
</style>
