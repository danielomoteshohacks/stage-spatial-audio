<script lang="ts">
  // "Fit to my ears": a two-minute listening game that picks the measured head whose directions
  // you hear best (decision 0026). A short burst plays from a direction through one candidate
  // head; tap the circle where it seemed to come from (front is up) and choose how high. Four
  // heads times six directions is 24 bursts. The head with the smallest error and the fewest
  // front-back mix-ups is kept on this device and sent with every render. Answers can be exported
  // as a CSV, so results before and after can be compared on willing listeners.
  import { onDestroy } from "svelte";
  import {
    DEFAULT_HEAD,
    saveHead,
    selectHead,
    trialOrder,
    trialsCsv,
    type Trial,
  } from "../lib/calibration";
  import { BackendError } from "../lib/api";
  import Icon from "./Icon.svelte";

  let { backend, ondone, onclose }: { backend: string; ondone: (head: string) => void; onclose: () => void } = $props();

  let phase: "intro" | "play" | "result" | "error" = $state("intro");
  let order: { head: string; az: number; el: number }[] = $state([]);
  let step = $state(0);
  let trials: Trial[] = $state([]);
  let answer: { az: number; el: number } | null = $state(null);
  let elChoice = $state(0);
  let started = 0;
  let message = $state("");
  let ctx: AudioContext | null = null;
  let chosen = $state(DEFAULT_HEAD);
  let scores: Record<string, { meanError: number; frontBack: number; n: number }> = $state({});
  let loading = $state(false);

  const ELEVATIONS = [
    { v: 0, label: "Level" },
    { v: 30, label: "Raised" },
    { v: 60, label: "Overhead" },
  ];

  async function begin() {
    try {
      const r = await fetch(`${backend}/v3/calibration/heads`);
      if (!r.ok) throw new BackendError(`The server answered HTTP ${r.status}.`, "server");
      const { heads } = (await r.json()) as { heads: { id: string }[] };
      const ids = heads.map((h) => h.id).slice(0, 4);
      if (ids.length < 2) throw new BackendError("Only one head is available on the server right now.", "server");
      order = trialOrder(ids);
      trials = [];
      step = 0;
      phase = "play";
      await playCurrent();
    } catch (e) {
      message = e instanceof Error ? e.message : "The game could not start.";
      phase = "error";
    }
  }

  async function playCurrent() {
    const t = order[step];
    if (!t) return;
    answer = null;
    elChoice = 0;
    loading = true;
    try {
      ctx ??= new AudioContext();
      if (ctx.state !== "running") await ctx.resume();
      const res = await fetch(`${backend}/v3/calibration/stimulus?head=${t.head}&az=${t.az}&el=${t.el}`);
      if (!res.ok) throw new BackendError("The sound could not be fetched.", "server");
      const buf = await ctx.decodeAudioData(await res.arrayBuffer());
      const src = new AudioBufferSourceNode(ctx, { buffer: buf });
      src.connect(ctx.destination);
      src.start();
      started = performance.now();
    } catch (e) {
      message = e instanceof Error ? e.message : "The sound could not be played.";
      phase = "error";
    } finally {
      loading = false;
    }
  }

  function tap(e: PointerEvent) {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const dx = e.clientX - (r.left + r.width / 2);
    const dy = e.clientY - (r.top + r.height / 2);
    answer = { az: (Math.atan2(-dx, -dy) * 180) / Math.PI, el: 0 };
  }

  async function next() {
    if (!answer) return;
    const t = order[step];
    trials = [...trials, { head: t.head, az: t.az, el: t.el, answerAz: answer.az, answerEl: elChoice, ms: performance.now() - started }];
    if (step + 1 >= order.length) {
      const r = selectHead(trials);
      chosen = r.best;
      scores = r.scores;
      saveHead(chosen, trials);
      phase = "result";
      return;
    }
    step += 1;
    await playCurrent();
  }

  function replay() {
    void playCurrent();
  }

  function csv() {
    const blob = new Blob([trialsCsv(trials, chosen)], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "soundstage-calibration.csv";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  onDestroy(() => void ctx?.close());
  const pad = $derived.by(() => {
    const a = answer as { az: number; el: number } | null;
    return a ? { x: Math.sin((-a.az * Math.PI) / 180), y: -Math.cos((a.az * Math.PI) / 180) } : null;
  });
</script>

<div class="cal">
  <header>
    <h2>Fit to my ears</h2>
    <button type="button" class="btn icon ghost" onclick={onclose} aria-label="Close"><Icon name="close" /></button>
  </header>

  {#if phase === "intro"}
    <p>
      Wear headphones and find a quiet place. You will hear 24 short bursts of noise. After each one, tap the circle
      where it seemed to come from: the top is straight ahead, the bottom is behind you. Then say how high it was.
      It takes about two minutes, and there are no wrong answers: guess when you are not sure.
    </p>
    <p class="muted small">
      Different people hear the same measured head differently. This picks the one whose directions you hear best, and
      keeps your choice on this device.
    </p>
    <button type="button" class="btn primary" onclick={begin}>Start</button>
  {:else if phase === "play"}
    <p class="eyebrow" role="status">Sound {step + 1} of {order.length}</p>
    <div
      class="disc"
      role="button"
      tabindex="0"
      aria-label="Tap where the sound came from. Straight ahead is the top."
      onpointerdown={tap}
      onkeydown={(e) => {
        if (e.key === "ArrowLeft") answer = { az: Math.min(180, (answer?.az ?? 0) + 15), el: 0 };
        if (e.key === "ArrowRight") answer = { az: Math.max(-180, (answer?.az ?? 0) - 15), el: 0 };
        if (e.key === "ArrowUp") answer = { az: 0, el: 0 };
        if (e.key === "ArrowDown") answer = { az: 180, el: 0 };
      }}
    >
      <span class="lbl f">front</span><span class="lbl b">behind</span><span class="lbl l">left</span><span class="lbl r">right</span>
      <span class="you" aria-hidden="true"></span>
      {#if pad}<span class="mark" style:left="{50 + pad.x * 40}%" style:top="{50 + pad.y * 40}%" aria-hidden="true"></span>{/if}
    </div>
    <div class="els" role="group" aria-label="How high">
      {#each ELEVATIONS as e (e.v)}
        <button type="button" class="chip" aria-pressed={elChoice === e.v} onclick={() => (elChoice = e.v)}>{e.label}</button>
      {/each}
    </div>
    <div class="row">
      <button type="button" class="btn" onclick={replay} disabled={loading}>Hear it again</button>
      <button type="button" class="btn primary" onclick={next} disabled={!answer || loading}>
        {step + 1 >= order.length ? "Finish" : "Next"}
      </button>
    </div>
  {:else if phase === "result"}
    <p>
      The head that suited you best is <strong>{chosen}</strong>. It is saved on this device and used for every render
      from now on.
    </p>
    <table>
      <thead><tr><th>Head</th><th>Mean error</th><th>Front-back mix-ups</th></tr></thead>
      <tbody>
        {#each Object.entries(scores) as [h, s] (h)}
          <tr class:best={h === chosen}>
            <td>{h}</td><td>{Math.round(s.meanError)} degrees</td><td>{Math.round(s.frontBack * 100)} percent</td>
          </tr>
        {/each}
      </tbody>
    </table>
    <div class="row">
      <button type="button" class="btn" onclick={csv}><Icon name="download" size={16} />Export the answers</button>
      <button type="button" class="btn primary" onclick={() => ondone(chosen)}>Done</button>
    </div>
  {:else}
    <p role="alert">{message}</p>
    <button type="button" class="btn" onclick={onclose}>Close</button>
  {/if}
</div>

<style>
  .cal {
    display: grid;
    gap: var(--gap-4);
    padding-bottom: var(--gap-5);
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .disc {
    position: relative;
    width: min(300px, 78vw);
    aspect-ratio: 1;
    margin: 0 auto;
    border-radius: 50%;
    background: radial-gradient(circle, var(--surface) 0 30%, var(--surface-2) 31% 66%, var(--surface-3) 67%);
    border: 1px solid var(--hairline-strong);
    box-shadow: var(--shadow-2);
    touch-action: manipulation;
  }
  .lbl {
    position: absolute;
    font-size: var(--text-xs);
    color: var(--text-3);
  }
  .f {
    top: 6px;
    left: 50%;
    transform: translateX(-50%);
  }
  .b {
    bottom: 6px;
    left: 50%;
    transform: translateX(-50%);
  }
  .l {
    left: 8px;
    top: 50%;
    transform: translateY(-50%);
  }
  .r {
    right: 8px;
    top: 50%;
    transform: translateY(-50%);
  }
  .you {
    position: absolute;
    left: 50%;
    top: 50%;
    width: 14px;
    height: 14px;
    margin: -7px;
    border-radius: 50%;
    background: var(--text);
  }
  .mark {
    position: absolute;
    width: 26px;
    height: 26px;
    margin: -13px;
    border-radius: 50%;
    background: var(--accent);
    box-shadow: var(--shadow-play);
  }
  .els,
  .row {
    display: flex;
    gap: var(--gap-2);
    justify-content: center;
    flex-wrap: wrap;
  }
  table {
    border-collapse: collapse;
    font-size: var(--text-sm);
  }
  th,
  td {
    text-align: left;
    padding: var(--gap-2) var(--gap-3);
    border-bottom: 1px solid var(--hairline);
  }
  .best td {
    font-weight: 700;
  }
</style>
