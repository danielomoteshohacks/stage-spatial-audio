<script lang="ts">
  // A bottom sheet built on <dialog>: the browser handles focus trapping, Escape and inertness
  // of the page behind it. It slides up from the bottom on phones and sits centred on desktop.
  import type { Snippet } from "svelte";
  import Icon from "./Icon.svelte";

  let {
    open,
    title,
    onclose,
    full = false,
    bare = false,
    children,
  }: { open: boolean; title: string; onclose: () => void; full?: boolean; bare?: boolean; children: Snippet } = $props();

  let dialog: HTMLDialogElement | undefined = $state();

  $effect(() => {
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  });
</script>

<dialog
  bind:this={dialog}
  class="sheet"
  class:full
  class:bare
  aria-label={title}
  onclose={onclose}
  onclick={(e) => {
    if (e.target === dialog) onclose();
  }}
>
  <div class="panel glass">
    {#if !bare}
      <header>
        <h2>{title}</h2>
        <button class="btn icon ghost" type="button" onclick={onclose} aria-label="Close">
          <Icon name="close" />
        </button>
      </header>
    {/if}
    <div class="body">
      {@render children()}
    </div>
  </div>
</dialog>

<style>
  .sheet {
    padding: 0;
    margin: 0;
    border: 0;
    background: transparent;
    max-width: 100vw;
    max-height: 100dvh;
    width: 100%;
    height: 100%;
    color: inherit;
  }

  .sheet::backdrop {
    background: rgb(4 5 8 / 0.6);
    -webkit-backdrop-filter: blur(6px);
    backdrop-filter: blur(6px);
  }

  .sheet[open] {
    display: flex;
    align-items: flex-end;
    justify-content: center;
  }

  .panel {
    width: 100%;
    max-width: 640px;
    max-height: 88dvh;
    display: flex;
    flex-direction: column;
    border-bottom-left-radius: 0;
    border-bottom-right-radius: 0;
    animation: rise var(--dur-3) var(--ease-out);
    background: var(--glass-strong);
  }

  .full .panel {
    max-height: 100dvh;
    height: 100dvh;
    border-radius: 0;
  }

  /* A bare sheet draws its own top bar (the player); give it the safe-area inset instead. */
  .bare .body {
    padding: max(var(--gap-3), env(safe-area-inset-top)) 0 0;
  }

  .bare .panel {
    background: var(--bg);
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--gap-4) var(--gap-4) var(--gap-2) var(--gap-5);
  }

  h2 {
    font-size: var(--text-xl);
  }

  .body {
    overflow-y: auto;
    padding: 0 var(--gap-5) calc(var(--gap-6) + env(safe-area-inset-bottom));
  }

  @media (min-width: 720px) {
    .sheet[open] {
      align-items: center;
    }

    .panel {
      border-radius: var(--radius-lg);
    }
  }

  @keyframes rise {
    from {
      transform: translateY(24px);
      opacity: 0;
    }
  }
</style>
