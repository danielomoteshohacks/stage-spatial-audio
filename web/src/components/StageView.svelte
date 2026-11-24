<script lang="ts">
  // Every object of the plan around the listener's head, seen from above and behind. Positions
  // follow the playhead with the backend's own formulas (lib/scene.ts); each disc pulses with
  // its object stem's level. Drag a disc to move it on the floor, use the height slider for its
  // elevation, then re-render. The lead vocal, the bass and the kit are locked, as in the plan.
  import { onMount } from "svelte";
  import { fromFloor, objectAt, toXYZ, type Plan, type PlanObject } from "../lib/scene";
  import { STEM_LABELS } from "../lib/labels";
  import Icon from "./Icon.svelte";

  let {
    plan,
    levels,
    time,
    busy = false,
    onchange,
    onrerender,
  }: {
    plan: Plan;
    levels: Record<string, Float32Array>;
    time: number;
    busy?: boolean;
    onchange: (p: Plan) => void;
    onrerender: () => void;
  } = $props();

  const LEVEL_RATE = 50; // level frames per second (see levelEnvelope)
  const TILT = (38 * Math.PI) / 180;
  const MAX_DIST = 8;

  let canvas: HTMLCanvasElement | undefined = $state();
  let width = $state(320);
  let height = $derived(Math.round(width * 0.78));
  let selected: string | null = $state(null);
  let dragging = false;

  const COLOURS: Record<string, string> = { vocals: "#ff7a5c", drums: "#1fc8b4", bass: "#f4f1ea", other: "#f2c14e", mix: "#1fc8b4" };

  function isBed(o: PlanObject): boolean {
    return (o.source ?? "").endsWith(".ambient") && o.spread === 0;
  }

  function colour(o: PlanObject): string {
    return COLOURS[(o.source ?? "mix.direct").split(".")[0]] ?? "#1fc8b4";
  }

  /** Display radius for a distance: logarithmic, so 0.7 m and 8 m both fit on a phone. */
  function radiusFor(d: number): number {
    return Math.log1p(d) / Math.log1p(MAX_DIST);
  }

  function project(az: number, el: number, dist: number): { x: number; y: number; depth: number } {
    const r = radiusFor(dist);
    const [x, y, z] = toXYZ(az, el, 1);
    const k = Math.min(width, height) * 0.46;
    const cx = width / 2;
    const cy = height * 0.58;
    return { x: cx + x * r * k, y: cy - z * r * k * Math.cos(TILT) - y * r * k * Math.sin(TILT) * 1.6, depth: z };
  }

  function level(name: string): number {
    const env = levels[name];
    if (!env || !env.length) return 0;
    return env[Math.min(env.length - 1, Math.max(0, Math.floor(time * LEVEL_RATE)))];
  }

  function draw() {
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    const g = canvas.getContext("2d");
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, width, height);
    const k = Math.min(width, height) * 0.46;
    const cx = width / 2;
    const cy = height * 0.58;
    // Floor rings at 1, 2 and 4 m, drawn as ellipses in perspective.
    g.lineWidth = 1;
    for (const d of [1, 2, 4, 8]) {
      const r = radiusFor(d) * k;
      g.strokeStyle = `rgba(244, 241, 234, ${d === 8 ? 0.05 : 0.1})`;
      g.beginPath();
      g.ellipse(cx, cy, r, r * Math.cos(TILT), 0, 0, Math.PI * 2);
      g.stroke();
    }
    // The listener: a head with a small mark for the front.
    g.fillStyle = "rgba(244, 241, 234, 0.9)";
    g.beginPath();
    g.ellipse(cx, cy, 9, 9 * Math.cos(TILT) + 2, 0, 0, Math.PI * 2);
    g.fill();
    g.fillStyle = "#1fc8b4";
    g.beginPath();
    g.moveTo(cx - 4, cy - 9);
    g.lineTo(cx + 4, cy - 9);
    g.lineTo(cx, cy - 16);
    g.fill();
    // Objects, far ones first so near ones draw on top.
    const items = plan.stems
      .map((o) => {
        const p = objectAt(plan, o, time);
        const pts = p.spread > 0
          ? [project(p.az + p.spread / 2, p.el, p.dist), project(p.az - p.spread / 2, p.el, p.dist)]
          : [project(p.az, p.el, p.dist)];
        return { o, p, pts };
      })
      .sort((a, b) => b.pts[0].depth - a.pts[0].depth);
    for (const { o, p, pts } of items) {
      const c = colour(o);
      const lv = level(o.name);
      if (isBed(o)) {
        // A bed object surrounds the listener (sides, rear and above), so it is a ring.
        const r = radiusFor(p.dist) * k;
        g.strokeStyle = c + Math.round(60 + 120 * lv).toString(16).padStart(2, "0");
        g.lineWidth = 2 + 6 * lv;
        g.setLineDash([6, 8]);
        g.beginPath();
        g.ellipse(cx, cy - 10, r, r * Math.cos(TILT), 0, 0, Math.PI * 2);
        g.stroke();
        g.setLineDash([]);
        continue;
      }
      const r = 7 + 14 * Math.sqrt(lv);
      if (pts.length === 2) {
        g.strokeStyle = c + "55";
        g.lineWidth = 2;
        g.beginPath();
        g.moveTo(pts[0].x, pts[0].y);
        g.lineTo(pts[1].x, pts[1].y);
        g.stroke();
      }
      for (const pt of pts) {
        const glow = g.createRadialGradient(pt.x, pt.y, 0, pt.x, pt.y, r * 2.2);
        glow.addColorStop(0, c + "aa");
        glow.addColorStop(1, c + "00");
        g.fillStyle = glow;
        g.beginPath();
        g.arc(pt.x, pt.y, r * 2.2, 0, Math.PI * 2);
        g.fill();
        g.fillStyle = c;
        g.beginPath();
        g.arc(pt.x, pt.y, r * 0.55, 0, Math.PI * 2);
        g.fill();
      }
      if (o.name === selected) {
        g.strokeStyle = "#f4f1ea";
        g.lineWidth = 2;
        for (const pt of pts) {
          g.beginPath();
          g.arc(pt.x, pt.y, r * 0.55 + 5, 0, Math.PI * 2);
          g.stroke();
        }
      }
    }
  }

  $effect(() => {
    void [plan, time, width, selected];
    draw();
  });

  function hit(x: number, y: number): PlanObject | null {
    let best: { o: PlanObject; d: number } | null = null;
    for (const o of plan.stems) {
      const p = objectAt(plan, o, time);
      const pts = p.spread > 0 ? [project(p.az + p.spread / 2, p.el, p.dist), project(p.az - p.spread / 2, p.el, p.dist)] : [project(p.az, p.el, p.dist)];
      for (const pt of pts) {
        const d = Math.hypot(pt.x - x, pt.y - y);
        if (d < 28 && (!best || d < best.d)) best = { o, d };
      }
    }
    return best?.o ?? null;
  }

  function point(e: PointerEvent): { x: number; y: number } {
    const rect = canvas!.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function update(name: string, patch: Partial<PlanObject>) {
    onchange({ ...plan, stems: plan.stems.map((o) => (o.name === name ? { ...o, ...patch } : o)) });
  }

  function down(e: PointerEvent) {
    const { x, y } = point(e);
    const o = hit(x, y);
    selected = o?.name ?? null;
    if (o && !o.protected) {
      dragging = true;
      canvas!.setPointerCapture(e.pointerId);
    }
  }

  function move(e: PointerEvent) {
    if (!dragging || !selected) return;
    const o = plan.stems.find((s) => s.name === selected);
    if (!o) return;
    const { x, y } = point(e);
    const k = Math.min(width, height) * 0.46;
    const fx = (x - width / 2) / k;
    const fz = (height * 0.58 - y) / (k * Math.cos(TILT));
    const r = Math.min(1, Math.hypot(fx, fz));
    const { az } = fromFloor(fx, fz);
    // Back from display radius to metres (inverse of radiusFor).
    const dist = Math.max(0.5, Math.expm1(r * Math.log1p(MAX_DIST)));
    update(o.name, { az: Math.round(az), dist: Math.round(dist * 10) / 10 });
  }

  function up() {
    dragging = false;
  }

  function keyMove(e: KeyboardEvent) {
    const o = plan.stems.find((s) => s.name === selected);
    if (!o || o.protected) return;
    const step = e.shiftKey ? 15 : 5;
    if (e.key === "ArrowLeft") update(o.name, { az: Math.min(180, o.az + step) });
    else if (e.key === "ArrowRight") update(o.name, { az: Math.max(-180, o.az - step) });
    else if (e.key === "ArrowUp") update(o.name, { dist: Math.max(0.5, Math.round((o.dist - 0.2) * 10) / 10) });
    else if (e.key === "ArrowDown") update(o.name, { dist: Math.min(MAX_DIST, Math.round((o.dist + 0.2) * 10) / 10) });
    else return;
    e.preventDefault();
  }

  let sel = $derived(plan.stems.find((o) => o.name === selected) ?? null);

  onMount(() => {
    const ro = new ResizeObserver(([entry]) => (width = Math.round(entry.contentRect.width)));
    ro.observe(canvas!.parentElement!);
    return () => ro.disconnect();
  });
</script>

<div class="stage">
  <canvas
    bind:this={canvas}
    style:width={`${width}px`}
    style:height={`${height}px`}
    tabindex="0"
    aria-label="Stage view: objects around your head. Tap one to select it, drag to move it; arrow keys move the selected object."
    onpointerdown={down}
    onpointermove={move}
    onpointerup={up}
    onpointercancel={up}
    onkeydown={keyMove}
  ></canvas>

  <ul class="legend" aria-label="Objects">
    {#each plan.stems as o (o.name)}
      <li>
        <button type="button" class:on={o.name === selected} onclick={() => (selected = o.name)}>
          <span class="swatch" style:background={colour(o)}></span>
          {STEM_LABELS[o.name] ?? o.name}
          {#if o.protected}<span class="faint">locked</span>{/if}
          {#if o.motion}<span class="faint">moving</span>{/if}
          {#if isBed(o)}<span class="faint">all around</span>{/if}
        </button>
      </li>
    {/each}
  </ul>

  {#if sel}
    <div class="selected glass">
      <p><strong>{STEM_LABELS[sel.name] ?? sel.name}</strong>
        <span class="faint">{sel.az > 0 ? `${sel.az} degrees left` : sel.az < 0 ? `${-sel.az} degrees right` : "centre"}, {sel.dist} m</span></p>
      {#if sel.protected}
        <p class="faint">Locked: the lead vocal, the bass and the kit stay where the artist put them.</p>
      {:else}
        <label class="field-label" for="height">Height <span class="value">{Math.round(sel.el)} degrees</span></label>
        <input id="height" type="range" min="-20" max="80" step="5" value={sel.el} style:--fill={`${((sel.el + 20) / 100) * 100}%`}
          oninput={(e) => update(sel!.name, { el: Number((e.currentTarget as HTMLInputElement).value) })} />
      {/if}
    </div>
  {/if}

  <button class="btn primary rerender" type="button" disabled={busy} onclick={onrerender}>
    <Icon name="refresh" /> {busy ? "Rendering" : "Re-render with this stage"}
  </button>
</div>

<style>
  .stage {
    display: grid;
    gap: var(--gap-4);
  }

  canvas {
    display: block;
    touch-action: none;
    border-radius: var(--radius-md);
    background: radial-gradient(80% 70% at 50% 58%, rgb(31 200 180 / 0.08), transparent 70%);
  }

  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .legend button {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-height: 32px;
    padding: 0 10px;
    border-radius: var(--radius-pill);
    border: 1px solid var(--hairline);
    background: transparent;
    font-size: var(--text-xs);
    cursor: pointer;
  }

  .legend button.on {
    background: rgb(244 241 234 / 0.1);
  }

  .swatch {
    width: 10px;
    height: 10px;
    border-radius: 50%;
  }

  .selected {
    padding: var(--gap-4);
    border-radius: var(--radius-md);
    display: grid;
    gap: var(--gap-2);
    font-size: var(--text-sm);
  }

  .rerender {
    width: 100%;
  }
</style>
