<script lang="ts">
  // Blind listening test of the current track: the original, the v3 render and, if the listener
  // loads one, a reference rendering of the same song, under the letters A, B, C (D) in an order
  // that rotates so every condition lands on every letter equally often. Loudness is matched (each
  // turned down to the quietest; nothing is made louder) and all letters loop over the same span,
  // so switching is sample-locked with a 30 ms cross-fade, as in the player. Trials stay in this
  // browser; Export gives the CSV.
  import { onDestroy } from "svelte";
  import { balancedOrders, commonLoopSeconds, LETTERS, loadTrials, matchGains, MAX_CONDITIONS, rmsOf, saveTrials, toCsv, type Condition, type Trial } from "../lib/blindtest";

  let {
    ctx,
    track,
    conditions: base,
  }: {
    ctx: AudioContext;
    track: string;
    conditions: Condition[];
  } = $props();

  // The reference slot: a rendering of the same song the listener loaded themselves.
  let reference: Condition | null = $state(null);
  let referenceName = $state("");
  let referenceError = $state("");
  const conditions = $derived<Condition[]>(reference ? [...base, reference].slice(0, MAX_CONDITIONS) : base);
  let queue: string[][] = [];
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
    if (!queue.length || queue[0].length !== conditions.length) queue = balancedOrders(conditions.map((c) => c.id));
    const next = queue.shift() ?? conditions.map((c) => c.id);
    order = next.map((id) => conditions.find((c) => c.id === id)!);
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

  async function loadReference(e: Event) {
    const file = (e.currentTarget as HTMLInputElement).files?.[0];
    if (!file) return;
    referenceError = "";
    try {
      const buffer = await ctx.decodeAudioData(await file.arrayBuffer());
      // Resampled to the context rate by decodeAudioData; the loop span is the shortest letter.
      reference = { id: "reference", label: "Reference", buffer };
      referenceName = file.name;
    } catch {
      referenceError = "That file could not be decoded as audio. Try a WAV, MP3, M4A or FLAC.";
    }
  }

  function removeReference() {
    reference = null;
    referenceName = "";
  }

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
    const span = commonLoopSeconds(order.map((c) => c.buffer));
    if (!playing) {
      const when = ctx.currentTime + 0.05;
      nodes = order.map((c, k) => {
        const g = new GainNode(ctx, { gain: k === i ? gains[c.id] : 0 });
        g.connect(ctx.destination);
        return g;
      });
      sources = order.map((c, k) => {
        const s = new AudioBufferSourceNode(ctx, { buffer: c.buffer, loop: true, loopStart: 0, loopEnd: span });
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
      ...(reference ? { reference_file: referenceName } : {}),
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

  onDestroy(stop);
</script>

<div class="test">
  <p class="muted">Listen to each letter on headphones, as often as you like. They are the same excerpt, matched in loudness, in a new random order for every trial.</p>

  <div class="letters" style:--n={order.length} role="radiogroup" aria-label="Listen to">
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

  <section class="reference">
    <p class="eyebrow">Reference slot</p>
    <p class="faint small">
      Optional. Load a headphone rendering of this same song that you have the right to use, for example an Atmos-style binaural
      version, to hear it blind against SoundStage. It stays in this browser. Start it at the same point as the song, and it is
      compared on the stretch all letters share.
    </p>
    {#if reference}
      <div class="row">
        <span class="small">{referenceName}</span>
        <button class="btn ghost" type="button" onclick={removeReference}>Remove</button>
      </div>
    {:else}
      <label class="btn">
        Load a reference file
        <input type="file" accept="audio/*" onchange={loadReference} hidden />
      </label>
    {/if}
    {#if referenceError}<p class="small" role="alert">{referenceError}</p>{/if}
  </section>

  <section class="results">
    <p class="eyebrow">{trials.length} trial{trials.length === 1 ? "" : "s"} saved on this device</p>
    {#if trials.length}
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
    grid-template-columns: repeat(var(--n, 3), 1fr);
    gap: var(--gap-3);
  }

  .letters button {
    aspect-ratio: 1;
    border-radius: var(--radius-lg);
    border: 1px solid var(--hairline);
    background: var(--surface-2);
    font-family: var(--font-display);
    font-size: 2.5rem;
    cursor: pointer;
  }

  .letters button.active {
    background: var(--accent);
    color: var(--accent-ink);
    box-shadow: var(--shadow-play);
  }

  fieldset {
    border: 0;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--gap-2);
  }

  .segmented {
    display: grid;
    grid-auto-flow: column;
    grid-auto-columns: 1fr;
    gap: var(--gap-2);
  }

  .segmented button {
    min-height: 44px;
    border-radius: var(--radius-pill);
    border: 1px solid var(--hairline-strong);
    background: transparent;
    color: var(--text);
    font-weight: 600;
    cursor: pointer;
  }

  .segmented button[aria-checked="true"] {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--accent-ink);
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
    background: var(--accent-soft);
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

  .reference {
    display: grid;
    gap: var(--gap-2);
    padding: var(--gap-4);
    border-radius: var(--radius-md);
    background: var(--surface-2);
  }

  .results {
    display: grid;
    gap: var(--gap-2);
  }
</style>
