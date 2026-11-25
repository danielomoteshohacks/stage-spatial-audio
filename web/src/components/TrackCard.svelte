<script lang="ts">
  import type { Item } from "../lib/items";
  import Art from "./Art.svelte";

  let { item, size = 148, eager = false, onplay }: { item: Item; size?: number; eager?: boolean; onplay: (i: Item) => void } = $props();
</script>

<button type="button" class="card" style:--w="{size}px" onclick={() => onplay(item)}>
  <Art id={item.artId ?? item.id} src={item.artworkUrl} {size} radius={16} {eager} />
  <span class="t">{item.title}</span>
  <span class="a">{item.artist}</span>
  {#if item.licence}<span class="l">{item.licence}</span>{/if}
</button>

<style>
  .card {
    display: grid;
    gap: 2px;
    width: var(--w);
    padding: 0;
    border: 0;
    background: transparent;
    text-align: left;
    color: inherit;
    transition: transform var(--dur-2) var(--spring);
  }
  .card:active {
    transform: scale(0.97);
  }
  .card :global(.art) {
    margin-bottom: var(--gap-2);
  }
  .t,
  .a {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .t {
    font-weight: 600;
    font-size: var(--text-sm);
  }
  .a {
    font-size: var(--text-xs);
    color: var(--text-2);
  }
  .l {
    font-size: 0.6875rem;
    color: var(--text-3);
    letter-spacing: 0.02em;
  }
</style>
