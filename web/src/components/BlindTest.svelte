<script lang="ts">
  // Blind listening test of the current track: the original, the v2 render and, on request, the
  // v1 render, under the letters A, B, C in a random order, matched in loudness (each turned
  // down to the quietest; nothing is made louder). Switching is sample-locked with a 30 ms
  // cross-fade, as in the player. Trials stay in this browser; Export gives the CSV.
  import { onDestroy } from "svelte";
  import { loadTrials, matchGains, rmsOf, saveTrials, shuffle, toCsv, type Condition, type Trial } from "../lib/blindtest";

  let {
    ctx,
    track,
    conditions,
    onaddv1,
    addingV1 = false,
  }: {
    ctx: AudioContext;
    track: string;
    conditions: Condition[];
    onaddv1?: () => void;
    addingV1?: boolean;
  } = $props();

  const LETTERS = ["A", "B", "C"];
  let order: Condition[] = $state([]);
  let gains: Record<string, number> = $state({});
  let current: number | null = $state(null);
  let ranking: string[] = $state([]);
  let outside = $state("");
  let natural = $state("");
  let trials: Trial[] = $state(loadTrials());
  let playing = $state(false);
  let sources: AudioBufferSourceNode[] = [];
  let nodes: GainNode[] = [];

  function setup() {
    stop();
    order = shuffle(conditions);
    const levels = Object.fromEntries(conditions.map((c) => [c.id, rmsOf(Array.from({ length: c.buffer.numberOfChannels }, (_, i) => c.buffer.getChannelData(i)))]));
    gains = matchGains(levels);
    ranking = [];
    outside = natural = "";
    current = null;
  }

  $effect(() => {
    void conditions.length;
    setup();
  });

  function stop() {
    for (const s of sources) {
      try {
        s.stop();
      } catch {
        // already stopped
      }
      s.disconnect();
    }
    for (const n of nodes) n.disconnect();
    sources = [];
    nodes = [];
    playing = false;
  }

  async function listen(i: number) {
    if (ctx.state !== "running") await ctx.resume();
    if (!playing) {
      const when = ctx.currentTime + 0.05;
      nodes = order.map((c, k) => {
        const g = new GainNode(ctx, { gain: k === i ? gains[c.id] : 0 });
        g.connect(ctx.destination);
        return g;
      });
      sources = order.map((c, k) => {
        const s = new AudioBufferSourceNode(ctx, { buffer: c.buffer, loop: true });
        s.connect(nodes[k]);
        s.start(when);
        return s;
      });
      playing = true;
    } else {
      const now = ctx.currentTime;
      order.forEach((c, k) => {
        const p = nodes[k].gain;
        p.cancelScheduledValues(now);
        p.setValueAtTime(p.value, now);
        p.linearRampToValueAtTime(k === i ? gains[c.id] : 0, now + 0.03);
      });
    }
    current = i;
  }

  function rank(id: string) {
    ranking = ranking.includes(id) ? ranking.filter((r) => r !== id) : [...ranking, id];
  }

  let complete = $derived(ranking.length === order.length && outside !== "" && natural !== "");

  function save() {
    const t: Trial = {
      trial: trials.length + 1,
      at: new Date().toISOString(),
      track,
      order: order.map((c) => c.id),
      ranking,
      outside,
      natural,
      gains_db: Object.fromEntries(Object.entries(gains).map(([k, v]) => [k, 20 * Math.log10(v)])),
    };
    trials = [...trials, t];
    saveTrials(trials);
    setup();
  }

  function exportCsv() {
    const blob = new Blob([toCsv(trials)], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `soundstage-blind-test-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  function clearAll() {
    trials = [];
    saveTrials(trials);
  }

  const letter = (id: string) => LETTERS[order.findIndex((c) => c.id === id)] ?? "?";
  onDestroy(stop);
</script>

<div class="test">
  <p class="muted">Listen to each letter on headphones, as often as you like. They are the same excerpt, matched in loudness, in a new random order for every trial.</p>

  <div class="letters" role="radiogroup" aria-label="Listen to">
    {#each order as c, i (c.id)}
      <button type="button" role="radio" aria-checked={current === i} class:active={current === i} onclick={() => listen(i)}>{LETTERS[i]}</button>
    {/each}
  </div>
  {#if playing}
    <button class="btn" type="button" onclick={stop}>Stop</button>
  {/if}

  <fieldset>
    <legend class="eyebrow">Your ranking, best first</legend>
    <div class="chips">
      {#each order as c, i (c.id)}
        <button type="button" class:on={ranking.includes(c.id)} aria-pressed={ranking.includes(c.id)} onclick={() => rank(c.id)}>
          {LETTERS[i]}{#if ranking.includes(c.id)} <span class="n">{ranking.indexOf(c.id) + 1}</span>{/if}
        </button>
      {/each}
    </div>
    <p class="faint small">Tap them in order: your favourite first.</p>
  </fieldset>

  <fieldset>
    <legend class="eyebrow">Most outside my head</legend>
    <div class="segmented" role="radiogroup" aria-label="Most outside my head">
      {#each order as c, i (c.id)}
        <button type="button" role="radio" aria-checked={outside === c.id} onclick={() => (outside = c.id)}>{LETTERS[i]}</button>
      {/each}
    </div>
  </fieldset>

  <fieldset>
    <legend class="eyebrow">Most natural</legend>
    <div class="segmented" role="radiogroup" aria-label="Most natural">
      {#each order as c, i (c.id)}
        <button type="button" role="radio" aria-checked={natural === c.id} onclick={() => (natural = c.id)}>{LETTERS[i]}</button>
      {/each}
    </div>
  </fieldset>

  <button class="btn primary" type="button" disabled={!complete} onclick={save}>Save this trial</button>

  {#if onaddv1 && !conditions.some((c) => c.id === "v1")}
    <button class="btn" type="button" disabled={addingV1} onclick={onaddv1}>{addingV1 ? "Rendering v1" : "Add the v1 render as a third letter"}</button>
  {/if}

  <section class="results">
    <p class="eyebrow">{trials.length} trial{trials.length === 1 ? "" : "s"} saved on this device</p>
    {#if trials.length}
      <p class="faint small">Last: {letter(trials[trials.length - 1].ranking[0])} was ranked first (the letters are reshuffled now).</p>
      <div class="row">
        <button class="btn" type="button" onclick={exportCsv}>Export CSV</button>
        <button class="btn ghost" type="button" onclick={clearAll}>Clear</button>
      </div>
    {/if}
  </section>
</div>

<style>
  .test {
    display: grid;
    gap: var(--gap-5);
  }

  .letters {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: var(--gap-3);
  }

  .letters button {
    aspect-ratio: 1;
    border-radius: var(--radius-lg);
    border: 1px solid var(--hairline);
    background: rgb(244 241 234 / 0.05);
    font-family: var(--font-display);
    font-size: 2.5rem;
    cursor: pointer;
  }

  .letters button.active {
    background: var(--accent);
    color: var(--accent-ink);
    box-shadow: 0 8px 28px var(--lagoon-glow);
  }

  fieldset {
    border: 0;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--gap-2);
  }

  .chips {
    display: flex;
    gap: var(--gap-2);
  }

  .chips button {
    flex: 1;
    min-height: 44px;
    border-radius: var(--radius-pill);
    border: 1px solid var(--hairline);
    background: transparent;
    font-weight: 600;
    cursor: pointer;
  }

  .chips button.on {
    background: rgb(244 241 234 / 0.12);
  }

  .n {
    color: var(--lagoon);
  }

  .small {
    font-size: var(--text-xs);
  }

  .row {
    display: flex;
    gap: var(--gap-2);
  }

  .results {
    display: grid;
    gap: var(--gap-2);
  }
</style>
