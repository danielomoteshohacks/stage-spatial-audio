<script lang="ts">
  import { onMount } from "svelte";
  import type { LoopRegion } from "../lib/engine";
  import { formatPrecise } from "../lib/format";
  import { computePeaks, normalisePeaks } from "../lib/peaks";

  let {
    channels,
    duration,
    time,
    loop,
    onseek,
    onloop,
  }: {
    channels: Float32Array[];
    duration: number;
    time: number;
    loop: LoopRegion | null;
    onseek: (t: number) => void;
    onloop: (a: number, b: number) => void;
  } = $props();

  const BAR = 2;
  const GAP = 1;
  /** Movement in CSS pixels that turns a tap into a loop drag, so a shaky tap still seeks. */
  const DRAG_PX = 8;

  let canvas: HTMLCanvasElement | undefined = $state();
  let width = $state(0);
  let height = 96;
  let drag: { x0: number; t0: number; dragging: boolean; id: number } | null = null;
  let preview: { a: number; b: number } | null = $state(null);

  let peaks = $derived(
    width > 0 ? normalisePeaks(computePeaks(channels, Math.max(1, Math.floor(width / (BAR + GAP))))) : new Float32Array(0),
  );

  function css(name: string): string {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function draw() {
    if (!canvas || width === 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    const g = canvas.getContext("2d");
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, width, height);
    const played = duration ? (time / duration) * width : 0;
    const region = preview ?? (loop ? { a: loop.start, b: loop.end } : null);
    if (region && duration) {
      const x0 = (Math.min(region.a, region.b) / duration) * width;
      const x1 = (Math.max(region.a, region.b) / duration) * width;
      g.fillStyle = "rgba(245, 184, 61, 0.13)";
      g.fillRect(x0, 0, x1 - x0, height);
      g.fillStyle = css("--accent");
      g.fillRect(x0, 0, 2, height);
      g.fillRect(x1 - 2, 0, 2, height);
    }
    const mid = height / 2;
    const dim = "rgba(255, 255, 255, 0.26)";
    const accent = css("--accent");
    for (let i = 0; i < peaks.length; i++) {
      const x = i * (BAR + GAP);
      const h = Math.max(2, peaks[i] * (height - 8));
      g.fillStyle = x < played ? accent : dim;
      g.fillRect(x, mid - h / 2, BAR, h);
    }
    g.fillStyle = css("--text");
    g.fillRect(Math.min(width - 2, Math.max(0, played - 1)), 0, 2, height);
  }

  $effect(() => {
    void [peaks, time, loop, preview, width];
    draw();
  });

  onMount(() => {
    const ro = new ResizeObserver(([entry]) => (width = Math.floor(entry.contentRect.width)));
    if (canvas) ro.observe(canvas);
    return () => ro.disconnect();
  });

  function timeAt(e: PointerEvent): number {
    const rect = canvas!.getBoundingClientRect();
    return Math.max(0, Math.min(duration, ((e.clientX - rect.left) / rect.width) * duration));
  }

  function down(e: PointerEvent) {
    if (e.button !== 0) return;
    canvas!.setPointerCapture(e.pointerId);
    drag = { x0: e.clientX, t0: timeAt(e), dragging: false, id: e.pointerId };
  }

  function move(e: PointerEvent) {
    if (!drag || drag.id !== e.pointerId) return;
    if (!drag.dragging && Math.abs(e.clientX - drag.x0) > DRAG_PX) drag.dragging = true;
    if (drag.dragging) preview = { a: drag.t0, b: timeAt(e) };
  }

  function up(e: PointerEvent) {
    if (!drag || drag.id !== e.pointerId) return;
    if (drag.dragging) onloop(drag.t0, timeAt(e));
    else onseek(timeAt(e));
    drag = null;
    preview = null;
  }

  function key(e: KeyboardEvent) {
    const step = e.shiftKey ? 5 : 1;
    const map: Record<string, number> = {
      ArrowLeft: time - step,
      ArrowDown: time - step,
      ArrowRight: time + step,
      ArrowUp: time + step,
      PageDown: time - 10,
      PageUp: time + 10,
      Home: loop ? loop.start : 0,
      End: duration,
    };
    if (e.key in map) {
      e.preventDefault();
      onseek(Math.max(0, Math.min(duration, map[e.key])));
    }
  }
</script>

<div class="wrap">
  <canvas
    bind:this={canvas}
    style:height={`${height}px`}
    role="slider"
    tabindex="0"
    aria-label="Playback position. Tap to seek, drag to set a loop."
    aria-valuemin="0"
    aria-valuemax={Math.round(duration)}
    aria-valuenow={Math.round(time)}
    aria-valuetext={`${formatPrecise(time)} of ${formatPrecise(duration)}`}
    onpointerdown={down}
    onpointermove={move}
    onpointerup={up}
    onpointercancel={() => {
      drag = null;
      preview = null;
    }}
    onkeydown={key}
  ></canvas>
</div>

<style>
  .wrap {
    position: relative;
  }
  canvas {
    display: block;
    width: 100%;
    border-radius: 10px;
    touch-action: none;
    cursor: pointer;
  }
</style>
