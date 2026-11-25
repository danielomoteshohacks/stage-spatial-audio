<script lang="ts">
  // Make a spatial version of a song of your own. The whole song is processed by default; the
  // first seconds are ready quickly and play while the rest is made. Progress shows each step and
  // each chunk, so a long song is never a silent wait.
  import { CHARACTER_INFO, CHARACTERS, GENRES, motionLabel, type Character } from "../lib/labels";
  import type { JobOptions, JobState } from "../lib/v3";
  import DropZone from "./DropZone.svelte";
  import Icon from "./Icon.svelte";

  let {
    job,
    uploading,
    head,
    error,
    onstart,
    oncancel,
    oncalibrate,
  }: {
    job: JobState | null;
    uploading: number | null;
    head: string;
    error: string | null;
    onstart: (file: File, o: JobOptions) => void;
    oncancel: () => void;
    oncalibrate: () => void;
  } = $props();

  let file: File | null = $state(null);
  let preset: "fast" | "best" = $state("fast");
  let genre = $state("auto");
  let character: Character = $state("balanced");
  let motion = $state(0.5);
  let excerpt = $state(false);

  const running = $derived(uploading !== null || (job !== null && !job.done));
  const pct = $derived(job?.chunks_total ? Math.round(((job.chunks_done ?? 0) / job.chunks_total) * 100) : 0);

  function start() {
    if (!file) return;
    onstart(file, {
      preset,
      genre: genre === "auto" ? null : genre,
      character,
      motion,
      head,
      seconds: excerpt ? 60 : null,
    });
  }

  const STEPS: [string, string][] = [
    ["load", "Reading the song"],
    ["analyse", "Finding the tempo, sections and genre"],
    ["chunk", "Separating, placing and rendering, chunk by chunk"],
    ["guard", "Checking it against the original"],
    ["write", "Saving"],
  ];
  function stepState(id: string): "done" | "now" | "todo" {
    const s = job?.stage ?? "";
    const order = ["load", "analyse", "chunk", "guard", "write", "done"];
    const cur = s.startsWith("chunk") ? 2 : Math.max(0, order.indexOf(s));
    const mine = order.indexOf(id);
    return job?.done && job.status === "done" ? "done" : mine < cur ? "done" : mine === cur ? "now" : "todo";
  }
</script>

<main class="screen" id="main">
  <h1>Create</h1>
  <p class="muted lede">Upload a song you own. Only music you have the right to use, please.</p>

  {#if !running && !job?.done}
    <DropZone onfile={(f) => (file = f)} />
    {#if file}
      <section class="form matte">
        <p class="fname"><Icon name="headphones" size={18} /> {file.name}</p>

        <fieldset>
          <legend>How much care</legend>
          <div class="chips">
            <button type="button" class="chip" aria-pressed={preset === "fast"} onclick={() => (preset = "fast")}>Fast</button>
            <button type="button" class="chip" aria-pressed={preset === "best"} onclick={() => (preset = "best")}>Best</button>
          </div>
          <p class="small muted">
            {preset === "fast"
              ? "One vocal model and the six-part model; the rest by rules. The first seconds arrive soonest."
              : "Every separation level, the vocal ensemble and the model dereverberation. Slower; for songs you will keep."}
          </p>
        </fieldset>

        <label>Genre
          <select bind:value={genre}>{#each GENRES as g (g.id)}<option value={g.id}>{g.label}</option>{/each}</select>
        </label>

        <fieldset>
          <legend>Character</legend>
          <div class="chips">
            {#each CHARACTERS as c (c)}
              <button type="button" class="chip" aria-pressed={character === c} onclick={() => (character = c)}>{CHARACTER_INFO[c].label}</button>
            {/each}
          </div>
          <p class="small muted">{CHARACTER_INFO[character].detail}</p>
        </fieldset>

        <label>Motion: {motionLabel(motion)}
          <input type="range" min="0" max="1" step="0.05" bind:value={motion} />
        </label>

        <label class="check"><input type="checkbox" bind:checked={excerpt} /> Only the first minute (a quick try)</label>
        <p class="small muted">
          Head: <strong>{head}</strong>
          <button type="button" class="link" onclick={oncalibrate}>fit it to my ears</button>
        </p>
        <button type="button" class="btn primary" onclick={start}>Make it spatial</button>
      </section>
    {/if}
  {:else}
    <section class="progress matte" aria-live="polite">
      <h2>{uploading !== null && !job ? "Uploading" : job?.done ? "Done" : "Working"}</h2>
      {#if uploading !== null && !job}
        <div class="bar"><span style:width="{Math.round(uploading * 100)}%"></span></div>
      {:else}
        <ol>
          {#each STEPS as [id, label] (id)}
            <li class={stepState(id)}>
              <span class="mk" aria-hidden="true">{#if stepState(id) === "done"}<Icon name="check" size={14} />{/if}</span>
              <span>{label}{id === "chunk" && job?.chunks_total ? ` (${job.chunks_done ?? 0} of ${job.chunks_total})` : ""}</span>
            </li>
          {/each}
        </ol>
        <div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={pct} aria-label="Chunks rendered">
          <span style:width="{pct}%"></span>
        </div>
        {#if job?.time_to_first_sound_s !== undefined}
          <p class="small muted">First sound after {job.time_to_first_sound_s.toFixed(1)} s. It is already playing; the rest is still being made.</p>
        {/if}
      {/if}
      {#if error}<p role="alert" class="err">{error}</p>{/if}
      {#if !job?.done}<button type="button" class="btn" onclick={oncancel}>Cancel</button>{/if}
    </section>
  {/if}
  {#if error && !running && !job}<p role="alert" class="err">{error}</p>{/if}
</main>

<style>
  h1 {
    font-size: var(--text-hero);
  }
  .lede {
    margin: var(--gap-2) 0 var(--gap-5);
  }
  .form,
  .progress {
    margin-top: var(--gap-5);
    padding: var(--gap-5);
    display: grid;
    gap: var(--gap-4);
  }
  fieldset {
    border: 0;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--gap-2);
  }
  legend {
    font-weight: 600;
    margin-bottom: var(--gap-2);
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--gap-2);
  }
  label {
    display: grid;
    gap: var(--gap-2);
    font-weight: 600;
  }
  select {
    min-height: 44px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--hairline-strong);
    background: var(--surface);
    padding: 0 var(--gap-3);
  }
  .check {
    display: flex;
    align-items: center;
    font-weight: 400;
  }
  .fname {
    display: flex;
    align-items: center;
    gap: var(--gap-2);
    font-weight: 600;
    overflow-wrap: anywhere;
  }
  .link {
    border: 0;
    background: transparent;
    color: var(--accent);
    font-weight: 600;
    text-decoration: underline;
    min-height: 32px;
  }
  ol {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--gap-2);
  }
  li {
    display: flex;
    gap: var(--gap-3);
    align-items: center;
    color: var(--text-3);
  }
  li.now {
    color: var(--text);
    font-weight: 600;
  }
  li.done {
    color: var(--text-2);
  }
  .mk {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    border: 2px solid var(--hairline-strong);
    display: grid;
    place-items: center;
    flex: none;
  }
  .done .mk {
    background: var(--accent);
    border-color: transparent;
    color: var(--accent-ink);
  }
  .now .mk {
    border-color: var(--accent);
  }
  .bar {
    height: 8px;
    border-radius: 4px;
    background: var(--surface-3);
    overflow: hidden;
  }
  .bar span {
    display: block;
    height: 100%;
    background: var(--accent);
    transition: width var(--dur-3) var(--ease);
  }
  .err {
    color: var(--fail);
    font-weight: 600;
  }
</style>
