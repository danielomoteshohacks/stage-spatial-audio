<script lang="ts">
  // Every object of the plan around the listener, seen from above: front is up, left is left. A
  // dot's distance from the centre is its distance, its size grows with height, and a ring marks
  // the objects that have left the floor. Positions follow the playhead with the renderer's own
  // rules (lib/scene3.ts), so a riser lifts the pads on screen as it does in your ears. Below the
  // picture the same facts are a list, so the stage can be read without seeing it.
  import { onMount } from "svelte";
  import { placeObjects, ROLE_LABELS, toScreen, type Plan3 } from "../lib/scene3";

  let { plan, time }: { plan: Plan3; time: number } = $props();

  let canvas: HTMLCanvasElement | undefined = $state();
  let width = $state(320);
  const height = $derived(Math.round(width * 0.9));
  const placed = $derived(placeObjects(plan, time));

  const COLOURS: Record<string, string> = {
    lead_vocal: "#c4432a", backing_vocal: "#d9822b", kick: "#0a8576", snare: "#0a8576", bass: "#55504a",
    cymbals: "#0a8576", toms: "#0a8576", guitar: "#6a5acd", keys: "#3a7bd5", pad: "#a4568a", fx: "#c08a00",
    other: "#6b655d", return: "#8a8f98",
  };

  function dirWord(az: number, el: number): string {
    const side = Math.abs(az) < 15 ? "front" : Math.abs(az) > 150 ? "behind" : az > 0
      ? (Math.abs(az) < 60 ? "front left" : Math.abs(az) < 120 ? "left" : "rear left")
      : (Math.abs(az) < 60 ? "front right" : Math.abs(az) < 120 ? "right" : "rear right");
    return el >= 25 ? `${side}, above` : el >= 8 ? `${side}, slightly raised` : side;
  }

  function draw() {
    const c = canvas;
    if (!c) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    c.width = width * dpr;
    c.height = height * dpr;
    const g = c.getContext("2d");
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const cs = getComputedStyle(c);
    const line = cs.getPropertyValue("--hairline-strong").trim() || "#ccc";
    const text = cs.getPropertyValue("--text-3").trim() || "#777";
    g.clearRect(0, 0, width, height);
    const cx = width / 2;
    const cy = height * 0.56;
    const R = Math.min(width * 0.46, height * 0.5);
    g.strokeStyle = line;
    g.lineWidth = 1;
    for (const r of [1 / 3, 2 / 3, 1]) {
      g.beginPath();
      g.arc(cx, cy, R * r, 0, Math.PI * 2);
      g.stroke();
    }
    g.fillStyle = text;
    g.font = "11px 'Instrument Sans', sans-serif";
    g.textAlign = "center";
    g.fillText("front", cx, cy - R - 6);
    g.fillText("rear", cx, cy + R + 14);
    // The listener.
    g.beginPath();
    g.arc(cx, cy, 6, 0, Math.PI * 2);
    g.fillStyle = cs.getPropertyValue("--text").trim() || "#222";
    g.fill();
    for (const o of placed) {
      const col = COLOURS[o.role] ?? "#6b655d";
      for (const f of o.feeds) {
        const [dx, dy] = toScreen(f.az, o.kind === "return" ? 3 : o.dist, R);
        const rad = 5 + Math.max(0, f.el) / 12;
        g.globalAlpha = o.kind === "return" ? 0.4 : 0.92;
        g.beginPath();
        g.arc(cx + dx, cy + dy, rad, 0, Math.PI * 2);
        g.fillStyle = col;
        g.fill();
        if (f.el >= 25) {
          g.globalAlpha = 0.8;
          g.strokeStyle = col;
          g.lineWidth = 1.5;
          g.beginPath();
          g.arc(cx + dx, cy + dy, rad + 4, 0, Math.PI * 2);
          g.stroke();
        }
      }
    }
    g.globalAlpha = 1;
  }

  $effect(() => {
    void placed;
    void width;
    draw();
  });

  onMount(() => {
    const ro = new ResizeObserver((es) => {
      width = Math.max(240, Math.round(es[0].contentRect.width));
    });
    if (canvas?.parentElement) ro.observe(canvas.parentElement);
    return () => ro.disconnect();
  });
</script>

<div class="stage matte">
  <canvas bind:this={canvas} style:width="{width}px" style:height="{height}px" aria-hidden="true"></canvas>
  <ul class="legend" aria-label="Where each part is now">
    {#each placed.filter((p) => p.kind === "object") as o (o.name)}
      <li>
        <span class="dot" style:background={COLOURS[o.role] ?? "#6b655d"}></span>
        <span class="n">{ROLE_LABELS[o.role] ?? o.name}{o.protected ? " (fixed)" : ""}</span>
        <span class="w">{dirWord(o.az, o.el)}</span>
      </li>
    {/each}
    {#if placed.some((p) => p.kind === "return")}
      <li><span class="dot ret"></span><span class="n">The record's reverb</span><span class="w">around and above</span></li>
    {/if}
  </ul>
</div>

<style>
  .stage {
    padding: var(--gap-4);
    display: grid;
    gap: var(--gap-3);
  }
  canvas {
    display: block;
    margin: 0 auto;
    max-width: 100%;
  }
  .legend {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 6px;
    font-size: var(--text-sm);
  }
  li {
    display: grid;
    grid-template-columns: 12px 1fr auto;
    align-items: center;
    gap: var(--gap-3);
  }
  .dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
  }
  .dot.ret {
    background: #8a8f98;
    opacity: 0.5;
  }
  .w {
    color: var(--text-2);
    font-size: var(--text-xs);
  }
</style>
