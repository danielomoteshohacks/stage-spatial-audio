<script lang="ts">
  // The Original / Spatial switch. A glossy pill whose thumb morphs across (stretching, then
  // settling), while the player cross-fades the two signals in 30 ms, sample-locked: the switch
  // never restarts playback. Space or S toggles it from the keyboard.
  import type { Side } from "../lib/engine";

  let { side, onchange }: { side: Side; onchange: (s: Side) => void } = $props();
</script>

<div class="switch" role="radiogroup" aria-label="Listen to">
  <span class="thumb" class:right={side === "spatial"} aria-hidden="true"></span>
  <button type="button" role="radio" aria-checked={side === "original"} onclick={() => onchange("original")}>
    Original
  </button>
  <button type="button" role="radio" aria-checked={side === "spatial"} onclick={() => onchange("spatial")}>
    Spatial
  </button>
</div>

<style>
  .switch {
    position: relative;
    display: grid;
    grid-template-columns: 1fr 1fr;
    padding: 5px;
    border-radius: var(--radius-pill);
    background: rgb(244 241 234 / 0.06);
    border: 1px solid var(--hairline);
    border-top-color: var(--hairline-top);
    box-shadow: inset 0 1px 0 rgb(255 255 255 / 0.04), var(--shadow-1);
    isolation: isolate;
  }

  .thumb {
    position: absolute;
    z-index: -1;
    top: 5px;
    bottom: 5px;
    left: 5px;
    width: calc(50% - 5px);
    border-radius: var(--radius-pill);
    background:
      linear-gradient(180deg, rgb(255 255 255 / 0.22), rgb(255 255 255 / 0) 55%),
      var(--accent-2);
    box-shadow: 0 6px 20px var(--coral-glow), inset 0 1px 0 rgb(255 255 255 / 0.35);
    transition: transform var(--dur-3) var(--ease-out), background-color var(--dur-2) var(--ease);
  }

  .thumb.right {
    transform: translateX(100%);
    background:
      linear-gradient(180deg, rgb(255 255 255 / 0.22), rgb(255 255 255 / 0) 55%),
      var(--accent);
    box-shadow: 0 6px 20px var(--lagoon-glow), inset 0 1px 0 rgb(255 255 255 / 0.35);
    animation: morph-right var(--dur-3) var(--ease-out);
  }

  .thumb:not(.right) {
    animation: morph-left var(--dur-3) var(--ease-out);
  }

  button {
    min-height: 48px;
    border: 0;
    background: transparent;
    border-radius: var(--radius-pill);
    font-size: var(--text-md);
    font-weight: 600;
    color: var(--ivory-2);
    cursor: pointer;
    transition: color var(--dur-2) var(--ease);
  }

  button[aria-checked="true"] {
    color: var(--accent-ink);
  }

  /* The morph: the thumb stretches toward its destination, then settles. */
  @keyframes morph-right {
    0% { transform: translateX(0) scaleX(1); }
    45% { transform: translateX(45%) scaleX(1.25); }
    100% { transform: translateX(100%) scaleX(1); }
  }

  @keyframes morph-left {
    0% { transform: translateX(100%) scaleX(1); }
    45% { transform: translateX(55%) scaleX(1.25); }
    100% { transform: translateX(0) scaleX(1); }
  }
</style>
