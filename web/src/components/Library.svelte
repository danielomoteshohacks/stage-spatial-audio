<script lang="ts">
  // The listener's own renders, kept on this device (IndexedDB). They play offline and without
  // using the server or any data again.
  import type { Item } from "../lib/items";
  import { formatBytes } from "../lib/format";
  import Art from "./Art.svelte";
  import Icon from "./Icon.svelte";

  let {
    items,
    sizes,
    onplay,
    onremove,
    oncreate,
  }: {
    items: Item[];
    sizes: Record<string, number>;
    onplay: (i: Item, queue: Item[]) => void;
    onremove: (i: Item) => void;
    oncreate: () => void;
  } = $props();
</script>

<main class="screen" id="main">
  <h1>Library</h1>
  <p class="muted">Renders saved on this device. They play without a connection.</p>
  {#if items.length}
    <ul>
      {#each items as it (it.id)}
        <li>
          <button type="button" class="row" onclick={() => onplay(it, items)}>
            <Art id={it.artId ?? it.id} src={it.artworkUrl} size={56} radius={12} />
            <span class="meta">
              <span class="t">{it.title}</span>
              <span class="a">{it.artist}{it.licence ? ` · ${it.licence}` : ""}</span>
            </span>
          </button>
          {#if sizes[it.libraryId ?? ""]}<span class="sz">{formatBytes(sizes[it.libraryId ?? ""])}</span>{/if}
          <button type="button" class="del" onclick={() => onremove(it)} aria-label="Remove {it.title} from this device">
            <Icon name="trash" size={18} />
          </button>
        </li>
      {/each}
    </ul>
  {:else}
    <section class="empty matte">
      <h2>Nothing saved yet</h2>
      <p class="muted">Play a song from Browse, or make one of your own. When a render finishes it is kept here.</p>
      <button type="button" class="btn primary" onclick={oncreate}>Create</button>
    </section>
  {/if}
</main>

<style>
  h1 {
    font-size: var(--text-hero);
  }
  ul {
    list-style: none;
    margin: var(--gap-5) 0 0;
    padding: 0;
  }
  li {
    display: flex;
    align-items: center;
    gap: var(--gap-2);
    border-bottom: 1px solid var(--hairline);
  }
  .row {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: var(--gap-3);
    border: 0;
    background: transparent;
    padding: var(--gap-2) 0;
    text-align: left;
    color: inherit;
  }
  .meta {
    display: grid;
    min-width: 0;
  }
  .t {
    font-weight: 600;
  }
  .a,
  .sz {
    font-size: var(--text-xs);
    color: var(--text-2);
  }
  .del {
    width: 44px;
    height: 44px;
    border: 0;
    background: transparent;
    color: var(--text-2);
  }
  .empty {
    margin-top: var(--gap-5);
    padding: var(--gap-5);
    display: grid;
    gap: var(--gap-3);
    justify-items: start;
  }
</style>
