<script lang="ts">
  // The format badge on the player: Original or Spatial, like a format pill on a streaming app,
  // and an honest line under it about what is playing now. The switch is sample-locked: the same
  // moment of the song continues on the other side.
  import Icon from "./Icon.svelte";
  import type { Side } from "../lib/stream";

  let {
    side,
    spatialReady,
    progress,
    buffering = false,
    onchange,
  }: {
    side: Side;
    spatialReady: boolean;
    progress: number;
    buffering?: boolean;
    onchange: (s: Side) => void;
  } = $props();

  const status = $derived(
    buffering
      ? "Waiting for the spatial render to catch up"
      : side === "original"
        ? "You are hearing the original stereo"
        : spatialReady
          ? "You are hearing the SoundStage spatial render"
          : `Spatial is rendering, ${Math.round(progress * 100)} percent`,
  );
</script>

<div class="wrap">
  <div class="pill glossy" role="group" aria-label="Which version plays">
    <button type="button" aria-pressed={side === "original"} class="o" onclick={() => onchange("original")}>
      Original
    </button>
    <button type="button" aria-pressed={side === "spatial"} class="s" onclick={() => onchange("spatial")}>
      <Icon name="spatial" size={16} /> Spatial
    </button>
  </div>
  <p class="status" role="status" aria-live="polite">{status}</p>
</div>

<style>
  .wrap {
    display: grid;
    justify-items: center;
    gap: var(--gap-2);
  }
  .pill {
    display: inline-flex;
    padding: 4px;
    border-radius: var(--radius-pill);
  }
  button {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-height: 40px;
    padding: 0 var(--gap-5);
    border: 0;
    border-radius: var(--radius-pill);
    background: transparent;
    color: var(--text-2);
    font-weight: 600;
    transition: background var(--dur-2) var(--ease), color var(--dur-2) var(--ease),
      transform var(--dur-2) var(--spring);
  }
  button:active {
    transform: scale(0.94);
  }
  button[aria-pressed="true"].s {
    background: var(--accent);
    color: var(--accent-ink);
    box-shadow: var(--shadow-1);
  }
  button[aria-pressed="true"].o {
    background: var(--accent-2);
    color: #fff;
    box-shadow: var(--shadow-1);
  }
  .status {
    font-size: var(--text-xs);
    color: var(--text-2);
    min-height: 1.2em;
  }
</style>
