<script lang="ts">
  // The soft round play button: accent fill, a glossy highlight along the top edge, a layered
  // accent shadow, and a spring on press and on release. Reduced motion removes the spring.
  import Icon from "./Icon.svelte";

  let {
    playing,
    busy = false,
    size = 72,
    label,
    onclick,
  }: { playing: boolean; busy?: boolean; size?: number; label?: string; onclick: () => void } = $props();
</script>

<button
  type="button"
  class="play"
  class:busy
  style:--size="{size}px"
  aria-label={label ?? (playing ? "Pause" : "Play")}
  {onclick}
>
  <span class="face">
    {#if busy}
      <span class="spin" aria-hidden="true"></span>
    {:else}
      <Icon name={playing ? "pause" : "play"} size={Math.round(size * 0.42)} />
    {/if}
  </span>
</button>

<style>
  .play {
    width: var(--size);
    height: var(--size);
    border-radius: 50%;
    border: 0;
    padding: 0;
    background: var(--accent);
    color: var(--accent-ink);
    box-shadow: var(--shadow-play);
    display: grid;
    place-items: center;
    position: relative;
    transition: transform 520ms var(--spring-bounce), box-shadow 320ms var(--ease);
  }
  .play::before {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: 50%;
    background: linear-gradient(180deg, rgb(255 255 255 / 0.34), transparent 52%);
    pointer-events: none;
  }
  .play:hover {
    transform: scale(1.04);
  }
  .play:active {
    transform: scale(0.92);
    box-shadow: 0 1px 2px rgb(0 0 0 / 0.2);
    transition-duration: 90ms;
  }
  .face {
    position: relative;
    display: grid;
    place-items: center;
    /* The triangle's centre of mass sits left of its box; nudge it so it looks centred. */
  }
  .play :global(svg) {
    transform: translateX(0);
  }
  .spin {
    width: calc(var(--size) * 0.36);
    height: calc(var(--size) * 0.36);
    border-radius: 50%;
    border: 3px solid color-mix(in srgb, var(--accent-ink) 30%, transparent);
    border-top-color: var(--accent-ink);
    animation: turn 0.9s linear infinite;
  }
  @keyframes turn {
    to {
      transform: rotate(360deg);
    }
  }
</style>
