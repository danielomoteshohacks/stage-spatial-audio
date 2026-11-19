<script lang="ts">
  import { onDestroy } from "svelte";
  import Waveform from "./Waveform.svelte";
  import { ABPlayer, CROSSFADE_S, type Version } from "./lib/abPlayer";
  import { decodeFile, getContext } from "./lib/audio";
  import { pairFiles } from "./lib/pairing";
  import { computePeaks, type Peaks } from "./lib/peaks";
  import { formatTime, spokenTime } from "./lib/time";

  interface Pair {
    id: number;
    originalName: string;
    stageName: string;
    original: AudioBuffer;
    stage: AudioBuffer;
    peaks: Record<Version, Peaks>;
    guessed: boolean;
  }

  const SEEK_STEP_S = 5;
  const WAVE_BUCKETS = 600;

  let library = $state<Pair[]>([]);
  let current = $state<Pair | null>(null);
  let player: ABPlayer | null = null;
  let playing = $state(false);
  let version = $state<Version>("original");
  let position = $state(0);
  let duration = $state(0);
  let loading = $state(false);
  let error = $state("");
  let dragOver = $state(false);
  let nextId = 1;
  let frame = 0;
  let fileInput: HTMLInputElement | undefined = $state();

  const stripExt = (name: string) => name.replace(/\.[^.]+$/, "");
  const versionLabel = (v: Version) => (v === "original" ? "Original" : "Stage");

  function sync() {
    if (!player) return;
    playing = player.isPlaying;
    version = player.version;
    position = player.position;
    duration = player.duration;
  }

  function loop() {
    if (!player) return;
    player.tick();
    sync();
    frame = playing ? requestAnimationFrame(loop) : 0;
  }

  function startLoop() {
    if (!frame) frame = requestAnimationFrame(loop);
  }

  function select(pair: Pair, keepPosition = false) {
    const at = keepPosition && player ? player.position : 0;
    const v = keepPosition && player ? player.version : "original";
    const wasPlaying = keepPosition && player ? player.isPlaying : false;
    player?.dispose();
    player = new ABPlayer(getContext(), pair.original, pair.stage);
    player.setVersion(v);
    player.seek(at);
    current = pair;
    if (wasPlaying) {
      player.play();
      startLoop();
    }
    sync();
  }

  async function addFiles(list: FileList | File[] | null | undefined) {
    const files = Array.from(list ?? []);
    error = "";
    const paired = pairFiles(files);
    if (!paired.ok) {
      error = paired.error;
      return;
    }
    loading = true;
    try {
      const ctx = getContext();
      const [original, stage] = await Promise.all([
        decodeFile(ctx, paired.original),
        decodeFile(ctx, paired.stage),
      ]);
      const pair: Pair = {
        id: nextId++,
        originalName: paired.original.name,
        stageName: paired.stage.name,
        original,
        stage,
        peaks: {
          original: computePeaks(original, WAVE_BUCKETS),
          stage: computePeaks(stage, WAVE_BUCKETS),
        },
        guessed: paired.guessed,
      };
      library = [...library, pair];
      select(library[library.length - 1] as Pair);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      loading = false;
      if (fileInput) fileInput.value = "";
    }
  }

  function swapCurrent() {
    if (!current) return;
    const swapped: Pair = {
      ...current,
      originalName: current.stageName,
      stageName: current.originalName,
      original: current.stage,
      stage: current.original,
      peaks: { original: current.peaks.stage, stage: current.peaks.original },
      guessed: false,
    };
    library = library.map((p) => (p.id === swapped.id ? swapped : p));
    select(swapped, true);
  }

  function removePair(pair: Pair) {
    library = library.filter((p) => p.id !== pair.id);
    if (current?.id === pair.id) {
      player?.dispose();
      player = null;
      current = null;
      playing = false;
      position = 0;
      duration = 0;
      version = "original";
    }
  }

  function togglePlay() {
    if (!player) return;
    // Resume inside the gesture: iOS only unlocks audio from a direct user action.
    void getContext().resume();
    player.toggle();
    sync();
    if (player.isPlaying) startLoop();
  }

  function setVersion(v: Version) {
    if (!player) return;
    player.setVersion(v);
    sync();
  }

  function seekTo(seconds: number) {
    if (!player) return;
    player.seek(seconds);
    sync();
  }

  function onKey(e: KeyboardEvent) {
    if (!player || e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target as HTMLElement | null;
    const tag = t?.tagName;
    const inText = tag === "INPUT" && (t as HTMLInputElement).type !== "range";
    if (inText || tag === "TEXTAREA" || t?.isContentEditable) return;
    const onButton = tag === "BUTTON" || tag === "SUMMARY";
    const onSlider = tag === "INPUT";
    switch (e.key) {
      case " ":
      case "k":
      case "K":
        if (onButton && e.key === " ") return; // the button handles its own Space
        e.preventDefault();
        togglePlay();
        break;
      case "a":
      case "A":
        setVersion("original");
        break;
      case "b":
      case "B":
        setVersion("stage");
        break;
      case "x":
      case "X":
        setVersion(version === "original" ? "stage" : "original");
        break;
      case "ArrowLeft":
        if (onSlider) return;
        e.preventDefault();
        seekTo(player.position - SEEK_STEP_S);
        break;
      case "ArrowRight":
        if (onSlider) return;
        e.preventDefault();
        seekTo(player.position + SEEK_STEP_S);
        break;
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    dragOver = false;
    void addFiles(e.dataTransfer?.files);
  }

  onDestroy(() => {
    if (frame) cancelAnimationFrame(frame);
    player?.dispose();
  });

  const mismatchMs = $derived(
    current ? Math.abs(current.original.duration - current.stage.duration) * 1000 : 0,
  );
</script>

<svelte:window onkeydown={onKey} />
<svelte:document
  ondragover={(e) => {
    e.preventDefault();
    dragOver = true;
  }}
  ondragleave={(e) => {
    if (!e.relatedTarget) dragOver = false;
  }}
  ondrop={onDrop}
/>

<div class="shell" class:drag={dragOver}>
  <aside class="side" aria-labelledby="library-heading">
    <div class="brand">
      <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true">
        <path d="M6 22 Q16 4 26 22" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" />
        <circle cx="16" cy="21" r="3" fill="currentColor" />
      </svg>
      <span>Stage</span>
    </div>

    <h2 id="library-heading">Library</h2>
    <p class="hint">This session only. Files stay on this device and are not saved.</p>
    {#if library.length === 0}
      <p class="empty">No pairs loaded yet.</p>
    {:else}
      <ul class="library">
        {#each library as pair (pair.id)}
          <li class:active={current?.id === pair.id}>
            <button
              class="item"
              onclick={() => select(pair)}
              aria-current={current?.id === pair.id ? "true" : undefined}
            >
              <span class="item-title">{stripExt(pair.originalName)}</span>
              <span class="item-sub">vs {stripExt(pair.stageName)} · {formatTime(Math.min(pair.original.duration, pair.stage.duration))}</span>
            </button>
            <button
              class="icon"
              onclick={() => removePair(pair)}
              aria-label="Remove {pair.originalName} and {pair.stageName} from the library"
              title="Remove"
            >
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" /></svg>
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </aside>

  <header class="top">
    <h1>A/B listening</h1>
    <p class="engine" role="status">
      <span class="dot" aria-hidden="true"></span>
      <strong>Engine status:</strong> rendering still runs offline in Python
      (<code>scripts/render_clip.py</code>). The browser engine is not built yet: this page only plays
      two files you already rendered.
    </p>
  </header>

  <main class="main">
    <section
      class="drop"
      class:over={dragOver}
      aria-labelledby="load-heading"
    >
      <h2 id="load-heading">Load a pair</h2>
      <p>
        Drop the two files from <code>render_clip.py</code> here: <code>input_stereo.wav</code> (the
        original) and <code>input_stage.wav</code> (the Stage render). Or choose them:
      </p>
      <label class="button primary">
        Choose two files
        <input
          bind:this={fileInput}
          class="visually-hidden"
          type="file"
          accept="audio/*,.wav"
          multiple
          onchange={(e) => addFiles((e.currentTarget as HTMLInputElement).files)}
        />
      </label>
      {#if loading}<p role="status">Decoding…</p>{/if}
      {#if error}<p class="error" role="alert">{error}</p>{/if}
    </section>

    {#if current}
      <section class="track" aria-labelledby="track-heading">
        <h2 id="track-heading">{stripExt(current.originalName)}</h2>
        <p class="meta">
          Original: {current.originalName} · Stage: {current.stageName} · {formatTime(duration)}
        </p>

        {#if current.guessed}
          <p class="note">
            The file names do not say which one is the Stage render, so the first file is treated as
            the original.
            <button class="link" onclick={swapCurrent}>Swap them</button>
          </p>
        {/if}
        {#if mismatchMs > 1}
          <p class="note">
            The files differ in length by {mismatchMs.toFixed(0)} ms; playback stops at the shorter one.
            They may not be a matching pair.
          </p>
        {/if}

        <div class="ab" role="group" aria-label="Version">
          <button
            class="seg"
            aria-pressed={version === "original"}
            onclick={() => setVersion("original")}
          >
            <span class="key" aria-hidden="true">A</span> Original
          </button>
          <button class="seg" aria-pressed={version === "stage"} onclick={() => setVersion("stage")}>
            <span class="key" aria-hidden="true">B</span> Stage
          </button>
        </div>
        <p class="hint">
          Both play in sync; switching keeps the position and crossfades in {Math.round(CROSSFADE_S * 1000)} ms. Loudness is matched
          in the files. Use headphones.
        </p>

        <Waveform
          peaks={current.peaks[version]}
          progress={duration > 0 ? position / duration : 0}
          onseek={(f) => seekTo(f * duration)}
        />

        <details class="keys">
          <summary>Keyboard</summary>
          <ul>
            <li><kbd>Space</kbd> or <kbd>K</kbd>: play or pause</li>
            <li><kbd>A</kbd>: original, <kbd>B</kbd>: Stage, <kbd>X</kbd>: switch</li>
            <li><kbd>←</kbd> <kbd>→</kbd>: back or forward {SEEK_STEP_S} seconds</li>
          </ul>
        </details>
      </section>
    {/if}
  </main>

  <section class="bar" aria-label="Player">
    <button
      class="play"
      onclick={togglePlay}
      disabled={!current}
      aria-label={playing ? "Pause" : "Play"}
      aria-describedby={current ? undefined : "bar-disabled"}
    >
      {#if playing}
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M7 5h4v14H7zM13 5h4v14h-4z" fill="currentColor" /></svg>
      {:else}
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M8 5v14l11-7z" fill="currentColor" /></svg>
      {/if}
    </button>
    <div class="now">
      {#if current}
        <span class="now-title">{stripExt(current.originalName)}</span>
        <span class="now-version" aria-live="polite">{playing ? "Playing" : "Paused"}: {versionLabel(version)}</span>
      {:else}
        <span class="now-title" id="bar-disabled">Load a pair to enable playback</span>
      {/if}
    </div>
    <div class="seek">
      <span class="time" aria-hidden="true">{formatTime(position)}</span>
      <input
        type="range"
        min="0"
        max={duration || 0}
        step="0.01"
        value={position}
        disabled={!current}
        aria-label="Seek"
        aria-valuetext="{spokenTime(position)} of {spokenTime(duration)}"
        oninput={(e) => seekTo(Number((e.currentTarget as HTMLInputElement).value))}
        style="--fill: {duration > 0 ? (position / duration) * 100 : 0}%"
      />
      <span class="time" aria-hidden="true">{formatTime(duration)}</span>
    </div>
    <button
      class="switch"
      onclick={() => setVersion(version === "original" ? "stage" : "original")}
      disabled={!current}
      aria-label="Switch version, now {versionLabel(version)}"
    >
      A/B: <strong>{versionLabel(version)}</strong>
    </button>
  </section>

  <footer class="foot">
    Stage is an independent proposal, not affiliated with or endorsed by Spotify, Apple or Dolby.
  </footer>
</div>
