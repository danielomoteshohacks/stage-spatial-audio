<script lang="ts">
  import { greeting, type Item } from "../lib/items";
  import type { Shelf as ShelfT } from "../lib/v3";
  import { fromTrack } from "../lib/items";
  import Shelf from "./Shelf.svelte";

  let {
    recents,
    shelves,
    status,
    onplay,
    onbrowse,
    oncreate,
  }: {
    recents: Item[];
    shelves: ShelfT[];
    status: "checking" | "online" | "offline";
    onplay: (i: Item, queue: Item[]) => void;
    onbrowse: (genre?: string) => void;
    oncreate: () => void;
  } = $props();

  const hello = greeting(new Date().getHours());
  const spatial = $derived(shelves.find((s) => s.key === "made_for_spatial"));
  const others = $derived(shelves.filter((s) => s.key !== "made_for_spatial").slice(0, 4));
  const items = (s: ShelfT) => s.tracks.map(fromTrack);
</script>

<main class="screen" id="main">
  <h1 class="hero">{hello}</h1>
  <p class="muted lede">Every part of the song, placed around you, with the vocal and the bass left where they were.</p>


  <section class="make matte">
    <h2>Your own song</h2>
    <p class="muted">Upload a track you own and hear it spatialised, from the first seconds while the rest is made.</p>
    <button type="button" class="btn primary" onclick={oncreate}>Create</button>
  </section>

  {#if recents.length}
    <Shelf title="Jump back in" items={recents} onplay={(i) => onplay(i, recents)} first />
  {/if}

  {#if spatial}
    <Shelf first={!recents.length} title="Made for spatial" items={items(spatial)} onplay={(i) => onplay(i, items(spatial))} onmore={() => onbrowse("made_for_spatial")} />
  {/if}
  {#each others as s (s.key)}
    <Shelf title={s.title} items={items(s)} onplay={(i) => onplay(i, items(s))} onmore={() => onbrowse(s.key)} />
  {/each}

  {#if status === "checking" && !shelves.length}
    <!-- Reserve the shelves' space while the server answers, so nothing below jumps when they arrive. -->
    <div class="skeleton" aria-hidden="true">
      {#each [0, 1] as k (k)}
        <div class="sk-shelf"><span class="sk-title"></span><div class="sk-row">{#each [0, 1, 2] as j (j)}<span class="sk-card"></span>{/each}</div></div>
      {/each}
    </div>
    <p class="muted note" role="status">Waking the server. A sleeping server takes about a minute.</p>
  {:else if status === "offline" && !shelves.length}
    <section class="note matte">
      <h2>The server is not answering</h2>
      <p class="muted">
        The catalogue and new renders need it. Your saved songs still play from this device: open the Library.
      </p>
    </section>
  {/if}

</main>

<style>
  .hero {
    font-size: var(--text-hero);
    margin-top: var(--gap-4);
  }
  .lede {
    max-width: 38ch;
    margin-top: var(--gap-2);
  }
  .note,
  .make {
    margin-top: var(--gap-5);
    padding: var(--gap-5);
    display: grid;
    gap: var(--gap-3);
    justify-items: start;
  }
  .note {
    border: 0;
    background: transparent;
    box-shadow: none;
    padding-inline: 0;
  }
  .skeleton {
    display: grid;
    gap: var(--gap-5);
    margin-top: var(--gap-5);
  }
  .sk-title {
    display: block;
    width: 55%;
    height: 32px;
    border-radius: 8px;
    background: var(--surface-3);
  }
  .sk-row {
    display: flex;
    gap: var(--gap-3);
    margin-top: var(--gap-3);
    height: 215px;
    overflow: hidden;
  }
  .sk-card {
    flex: none;
    width: 148px;
    height: 148px;
    border-radius: 16px;
    background: var(--surface-3);
  }
  .make h2 {
    font-size: var(--text-xl);
  }
</style>
