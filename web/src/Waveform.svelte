<script lang="ts">
  import type { Peaks } from "./lib/peaks";

  interface Props {
    peaks: Peaks;
    /** 0..1 */
    progress: number;
    onseek: (fraction: number) => void;
  }

  let { peaks, progress, onseek }: Props = $props();

  let canvas: HTMLCanvasElement | undefined = $state();
  let width = $state(0);
  let height = $state(0);
  let dragging = false;

  function colour(name: string): string {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  $effect(() => {
    if (!canvas || width === 0 || height === 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    const g = canvas.getContext("2d");
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, width, height);
    const played = colour("--accent");
    const rest = colour("--wave-rest");
    const n = peaks.max.length;
    const bar = width / n;
    const mid = height / 2;
    const cut = progress * width;
    for (let i = 0; i < n; i++) {
      const x = i * bar;
      const hi = peaks.max[i] ?? 0;
      const lo = peaks.min[i] ?? 0;
      const top = mid - hi * mid * 0.95;
      const h = Math.max(1, (hi - lo) * mid * 0.95);
      g.fillStyle = x + bar / 2 <= cut ? played : rest;
      g.fillRect(x, top, Math.max(1, bar - 1), h);
    }
    g.fillStyle = colour("--text");
    g.fillRect(Math.min(width - 2, cut), 0, 2, height);
  });

  function fractionAt(e: PointerEvent): number {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    return Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
  }

  function down(e: PointerEvent) {
    dragging = true;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    onseek(fractionAt(e));
  }
  function move(e: PointerEvent) {
    if (dragging) onseek(fractionAt(e));
  }
  function up() {
    dragging = false;
  }
</script>

<!-- Pointer shortcut only; the seek slider in the player bar is the accessible control. -->
<div
  class="wave"
  bind:clientWidth={width}
  bind:clientHeight={height}
  onpointerdown={down}
  onpointermove={move}
  onpointerup={up}
  onpointercancel={up}
  aria-hidden="true"
>
  <canvas bind:this={canvas} style="width: {width}px; height: {height}px"></canvas>
</div>

<style>
  .wave {
    position: relative;
    width: 100%;
    height: 140px;
    cursor: pointer;
    touch-action: none;
    border-radius: 10px;
    background: var(--surface-2);
    overflow: hidden;
  }
  canvas {
    position: absolute;
    inset: 0;
    display: block;
  }
</style>
