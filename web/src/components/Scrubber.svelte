<script lang="ts">
  // The seek bar: a native range input (keyboard, screen reader and touch behave as the platform
  // does) drawn as a soft track with a filled part for the playhead and a lighter part for how
  // much of the spatial render exists yet. Dragging seeks on release, so a seek never restarts
  // playback many times.
  import { formatTime } from "../lib/format";

  let {
    time,
    duration,
    ready = duration,
    onseek,
  }: { time: number; duration: number; ready?: number; onseek: (t: number) => void } = $props();

  let dragging = $state(false);
  let drag = $state(0);
  const shown = $derived(dragging ? drag : time);
  const pct = $derived(duration > 0 ? (shown / duration) * 100 : 0);
  const readyPct = $derived(duration > 0 ? Math.min(100, (ready / duration) * 100) : 0);
</script>

<div class="scrub">
  <div class="track" style:--p="{pct}%" style:--r="{readyPct}%">
    <input
      type="range"
      min="0"
      max={Math.max(duration, 0.01)}
      step="0.1"
      value={shown}
      aria-label="Seek"
      aria-valuetext="{formatTime(shown)} of {formatTime(duration)}"
      oninput={(e) => {
        dragging = true;
        drag = Number((e.currentTarget as HTMLInputElement).value);
      }}
      onchange={(e) => {
        dragging = false;
        onseek(Number((e.currentTarget as HTMLInputElement).value));
      }}
    />
  </div>
  <div class="times">
    <span>{formatTime(shown)}</span>
    <span>{formatTime(duration)}</span>
  </div>
</div>

<style>
  .scrub {
    width: 100%;
  }
  .track {
    position: relative;
    height: 28px;
    display: grid;
    align-items: center;
  }
  .track::before {
    content: "";
    position: absolute;
    left: 0;
    right: 0;
    height: 6px;
    border-radius: 3px;
    background: linear-gradient(
      90deg,
      var(--accent) 0 var(--p),
      color-mix(in srgb, var(--accent) 24%, var(--surface-3)) var(--p) var(--r),
      var(--surface-3) var(--r) 100%
    );
    box-shadow: inset 0 1px 1px rgb(0 0 0 / 0.08);
  }
  input {
    position: relative;
    width: 100%;
    margin: 0;
    height: 28px;
    background: transparent;
    -webkit-appearance: none;
    appearance: none;
    cursor: pointer;
  }
  input::-webkit-slider-runnable-track {
    background: transparent;
    height: 28px;
  }
  input::-moz-range-track {
    background: transparent;
    height: 28px;
  }
  input::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 18px;
    height: 18px;
    margin-top: 5px;
    border-radius: 50%;
    border: 0;
    background: var(--surface);
    box-shadow: 0 0 0 2px var(--accent), var(--shadow-1);
    transition: transform var(--dur-2) var(--spring);
  }
  input::-moz-range-thumb {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    border: 0;
    background: var(--surface);
    box-shadow: 0 0 0 2px var(--accent), var(--shadow-1);
  }
  input:active::-webkit-slider-thumb {
    transform: scale(1.25);
  }
  .times {
    display: flex;
    justify-content: space-between;
    font-size: var(--text-xs);
    color: var(--text-2);
    margin-top: 2px;
  }
</style>
