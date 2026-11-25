<script lang="ts">
  import type { Item } from "../lib/items";
  import TrackCard from "./TrackCard.svelte";

  let {
    title,
    items,
    onplay,
    onmore,
    first = false,
  }: { title: string; items: Item[]; onplay: (i: Item) => void; onmore?: () => void; first?: boolean } = $props();
</script>

{#if items.length}
  <section class="shelf" aria-label={title}>
    <header>
      <h2>{title}</h2>
      {#if onmore}<button type="button" class="more" onclick={onmore}>See all</button>{/if}
    </header>
    <div class="scroller">
      {#each items as item, i (item.id)}
        <TrackCard {item} {onplay} eager={first && i < 3} />
      {/each}
    </div>
  </section>
{/if}

<style>
  .shelf {
    margin-top: var(--gap-5);
  }
  header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--gap-3);
  }
  h2 {
    font-size: var(--text-xl);
  }
  .more {
    border: 0;
    background: transparent;
    color: var(--accent);
    font-weight: 600;
    font-size: var(--text-sm);
    min-height: 44px;
    padding: 0 var(--gap-2);
  }
</style>
