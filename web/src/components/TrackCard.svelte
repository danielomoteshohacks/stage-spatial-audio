<script lang="ts">
  import type { Item } from "../lib/items";
  import Art from "./Art.svelte";

  let { item, size = 148, eager = false, onplay }: { item: Item; size?: number; eager?: boolean; onplay: (i: Item) => void } = $props();
</script>

<button type="button" class="card" style:--w="{size}px" onclick={() => onplay(item)}>
  <span class="cover">
    <Art id={item.artId ?? item.id} src={item.artworkUrl} {size} radius={16} {eager} />
    <!-- A small glossy play badge on the cover, as on a streaming app's cards. -->
    <span class="badge" aria-hidden="true"><svg viewBox="0 0 24 24" width="16" height="16"><path d="M8 5.5v13l10.5-6.5z" fill="currentColor" /></svg></span>
  </span>
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
  .cover {
    position: relative;
    display: block;
    margin-bottom: var(--gap-2);
  }
  .cover :global(.art) {
    box-shadow: var(--shadow-2), inset 0 0 0 1px rgb(0 0 0 / 0.06);
  }
  .badge {
    position: absolute;
    right: 8px;
    bottom: 8px;
    display: grid;
    place-items: center;
    width: 34px;
    height: 34px;
    border-radius: 50%;
    color: #fff;
    background: radial-gradient(circle at 35% 30%, color-mix(in oklab, var(--lagoon) 70%, #fff 30%), var(--lagoon) 65%);
    box-shadow: 0 4px 12px rgb(0 0 0 / 0.28), inset 0 1px 0 rgb(255 255 255 / 0.4);
    opacity: 0.94;
    transition: transform var(--dur-2) var(--spring-bounce);
  }
  .card:hover .badge {
    transform: scale(1.08);
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
