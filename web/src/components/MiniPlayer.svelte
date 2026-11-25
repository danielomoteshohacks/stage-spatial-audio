<script lang="ts">
  // The persistent bar above the tab bar: what is playing, which version you hear, play and pause,
  // and a thin progress line. Tapping it opens the full player.
  import type { Item } from "../lib/items";
  import type { Side } from "../lib/stream";
  import Art from "./Art.svelte";
  import Icon from "./Icon.svelte";
  import PlayButton from "./PlayButton.svelte";

  let {
    item,
    playing,
    busy,
    side,
    time,
    duration,
    onopen,
    ontoggle,
  }: {
    item: Item;
    playing: boolean;
    busy: boolean;
    side: Side;
    time: number;
    duration: number;
    onopen: () => void;
    ontoggle: () => void;
  } = $props();
  const pct = $derived(duration > 0 ? (time / duration) * 100 : 0);
</script>

<div class="mini glass" style:--p="{pct}%">
  <button type="button" class="open" onclick={onopen} aria-label="Open the player: {item.title}">
    <Art id={item.artId ?? item.id} src={item.artworkUrl} size={44} radius={10} />
    <span class="meta">
      <span class="t">{item.title}</span>
      <span class="a">
        <Icon name={side === "spatial" ? "spatial" : "headphones"} size={13} />
        {side === "spatial" ? "Spatial" : "Original"} · {item.artist}
      </span>
    </span>
  </button>
  <PlayButton {playing} {busy} size={44} onclick={ontoggle} />
</div>

<style>
  .mini {
    position: fixed;
    z-index: 25;
    left: var(--gap-2);
    right: var(--gap-2);
    bottom: calc(var(--nav-h) + var(--gap-2) + env(safe-area-inset-bottom));
    height: var(--mini-h);
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-2);
    display: flex;
    align-items: center;
    gap: var(--gap-3);
    padding: 0 var(--gap-3) 0 var(--gap-2);
    overflow: hidden;
  }
  .mini::after {
    content: "";
    position: absolute;
    left: 0;
    bottom: 0;
    height: 2px;
    width: var(--p);
    background: var(--accent);
  }
  .open {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: var(--gap-3);
    border: 0;
    padding: 0;
    background: transparent;
    text-align: left;
    color: inherit;
  }
  .meta {
    display: grid;
    min-width: 0;
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
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: var(--text-xs);
    color: var(--text-2);
  }
  @media (min-width: 900px) {
    .mini {
      left: calc(var(--nav-w) + var(--gap-4));
      bottom: var(--gap-4);
      max-width: 520px;
    }
  }
</style>
