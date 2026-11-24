<script lang="ts">
  import { onMount } from "svelte";
  import BackendSettings from "./components/BackendSettings.svelte";
  import DropZone from "./components/DropZone.svelte";
  import Icon from "./components/Icon.svelte";
  import Player from "./components/Player.svelte";
  import ProgressPanel from "./components/ProgressPanel.svelte";
  import RunReport from "./components/RunReport.svelte";
  import SoundControls from "./components/SoundControls.svelte";
  import {
    BackendError,
    checkBackend,
    diagnose,
    fetchArrayBuffer,
    fileUrl,
    runProcess,
    stemName,
    uploadFile,
    type Diagnosis,
    type ProcessOutput,
    type RunReport as Report,
    type StageState,
  } from "./lib/api";
  import { SyncPlayer } from "./lib/engine";
  import { orderProfiles } from "./lib/labels";
  import { loadBackendUrl, saveBackendUrl } from "./lib/settings";

  /** Gradio deletes uploads after 30 minutes; reuse an upload for re-renders well inside that. */
  const UPLOAD_REUSE_MS = 20 * 60 * 1000;

  let backend = $state(loadBackendUrl());
  let status: "checking" | "online" | "offline" = $state("checking");
  let diagnosis: Diagnosis | null = $state(null);
  let profiles: string[] = $state([]);
  let modes: string[] = $state(["lite", "stems"]);
  let settings: BackendSettings | undefined = $state();

  let file: File | null = $state(null);
  let duration: number | null = $state(null);
  let mode: "lite" | "stems" = $state("lite");
  let profile = $state("max");
  let beta = $state(2.0);
  /** null: let the backend start at the loudest part of the track. */
  let start: number | null = $state(null);
  let seconds = $state(30);

  let phase: "idle" | "uploading" | "processing" | "downloading" = $state("idle");
  let upload = $state(0);
  let stages: StageState[] = $state([]);
  let error: string | null = $state(null);
  let report: Report | null = $state(null);
  let notes: string[] = $state([]);
  let player: SyncPlayer | null = $state(null);
  let channels: { original: Float32Array[]; spatial: Float32Array[] } | null = $state(null);
  let resultName = $state("");
  let abort: AbortController | null = null;
  let uploaded: { file: File; path: string; at: number; backend: string } | null = null;
  let ctx: AudioContext | null = null;

  let busy = $derived(phase !== "idle");

  async function check() {
    status = "checking";
    diagnosis = null;
    try {
      const info = await checkBackend(backend);
      profiles = orderProfiles(info.profiles);
      modes = info.modes;
      if (!profiles.includes(profile)) profile = profiles[0];
      status = "online";
    } catch (e) {
      status = "offline";
      diagnosis =
        e instanceof BackendError && e.kind === "protocol"
          ? { title: "That address is not a SoundStage backend", detail: e.message, fixes: ["Check the address in Backend settings."] }
          : diagnose(backend, window.location);
    }
  }

  function saveBackend(url: string) {
    backend = saveBackendUrl(url);
    uploaded = null;
    void check();
  }

  function readDuration(f: File): Promise<number | null> {
    // Metadata only: the browser reads the header, not the whole file.
    return new Promise((resolve) => {
      const audio = new Audio();
      const url = URL.createObjectURL(f);
      const done = (v: number | null) => {
        URL.revokeObjectURL(url);
        resolve(v);
      };
      audio.preload = "metadata";
      audio.onloadedmetadata = () => done(Number.isFinite(audio.duration) ? audio.duration : null);
      audio.onerror = () => done(null);
      audio.src = url;
    });
  }

  async function pick(f: File) {
    file = f;
    error = null;
    duration = await readDuration(f);
    // The backend's default: 30 s from 30 s in, moved earlier for short tracks.
    start = null;
  }

  function audioContext(): AudioContext {
    ctx ??= new AudioContext({ latencyHint: "playback" });
    return ctx;
  }

  function onUpdate(out: ProcessOutput) {
    if (out[0]?.stages) stages = out[0].stages;
  }

  async function render() {
    if (!file || status !== "online") return;
    error = null;
    abort = new AbortController();
    const signal = abort.signal;
    // Created inside the click so mobile browsers allow it to start later.
    const audio = audioContext();
    void audio.resume().catch(() => undefined);
    try {
      let path: string;
      if (uploaded && uploaded.file === file && uploaded.backend === backend && Date.now() - uploaded.at < UPLOAD_REUSE_MS) {
        path = uploaded.path;
      } else {
        phase = "uploading";
        upload = 0;
        path = await uploadFile(backend, file, (f) => (upload = f), signal);
        uploaded = { file, path, at: Date.now(), backend };
      }
      phase = "processing";
      stages = [];
      const out = await runProcess(backend, path, file.name, { mode, profile, beta, start, seconds }, onUpdate, signal);
      const [progress, original, spatial, stems] = out;
      if (progress.error || !original || !spatial || !progress.run) {
        if (progress.error?.includes("did not arrive")) uploaded = null;
        throw new BackendError(progress.error ?? "The backend returned no audio.", "server");
      }
      phase = "downloading";
      const stemFiles = stems ?? [];
      const [ob, sb, ...stemBufs] = await Promise.all(
        [original, spatial, ...stemFiles].map(async (fd) => audio.decodeAudioData(await fetchArrayBuffer(fileUrl(backend, fd), signal))),
      );
      const stemMap: Record<string, AudioBuffer> = {};
      stemFiles.forEach((fd, i) => (stemMap[stemName(fd)] = stemBufs[i]));
      player?.dispose();
      player = new SyncPlayer(audio, { original: ob, spatial: sb, stems: stemMap });
      const chans = (b: AudioBuffer) => Array.from({ length: b.numberOfChannels }, (_, i) => b.getChannelData(i));
      channels = { original: chans(ob), spatial: chans(sb) };
      report = progress.run;
      notes = progress.notes ?? [];
      resultName = file.name;
    } catch (e) {
      if (e instanceof BackendError && e.kind === "cancelled") error = null;
      else if (e instanceof BackendError && e.kind === "unreachable") {
        error = e.message;
        void check();
      } else if (e instanceof DOMException && e.name === "EncodingError") {
        error = "This browser could not decode the rendered FLAC files.";
      } else {
        error = e instanceof Error ? e.message : String(e);
      }
    } finally {
      phase = "idle";
      abort = null;
    }
  }

  onMount(() => {
    void check();
  });
</script>

<div class="shell">
  <header class="top">
    <a class="brand" href="./" aria-label="SoundStage home">
      <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true">
        <circle cx="16" cy="20" r="3.2" fill="var(--accent)" />
        <path d="M9 20a7 7 0 0 1 14 0" fill="none" stroke="var(--accent)" stroke-width="2.4" stroke-linecap="round" />
        <path d="M4.5 20a11.5 11.5 0 0 1 23 0" fill="none" stroke="var(--accent)" stroke-opacity=".45" stroke-width="2.4" stroke-linecap="round" />
      </svg>
      <span>SoundStage</span>
    </a>
    <button type="button" class="pill" onclick={() => settings?.open()} aria-label={`Backend settings. Status: ${status}`}>
      <span class="led {status}" aria-hidden="true"></span>
      <span>{status === "online" ? "Connected" : status === "checking" ? "Connecting" : "Offline"}</span>
      <Icon name="settings" size={18} />
    </button>
  </header>

  <main>
    <section class="hero">
      <p class="eyebrow">Listening bench</p>
      <h1>Hear the record, then hear the stage.</h1>
      <p class="lede">
        Drop a track. SoundStage renders an excerpt, then plays the original and the spatial version in perfect sync so you can
        switch mid-phrase and tune by ear. Use headphones.
      </p>
    </section>

    {#if status === "offline" && diagnosis}
      <div class="notice error rise" role="alert">
        <Icon name="alert" size={20} />
        <div class="diag">
          <strong>{diagnosis.title}</strong>
          <p>{diagnosis.detail}</p>
          <ol>
            {#each diagnosis.fixes as fix (fix)}<li>{fix}</li>{/each}
          </ol>
          <div class="diag-actions">
            <button type="button" class="btn btn-sm" onclick={check}><Icon name="refresh" size={16} /> Check again</button>
            <button type="button" class="btn btn-sm btn-ghost" onclick={() => settings?.open()}>Change backend</button>
          </div>
        </div>
      </div>
    {/if}

    <div class="grid">
      <div class="col">
        <section class="card" aria-labelledby="track-title">
          <h2 id="track-title" class="section-title">Track</h2>
          <div class="stack">
            <DropZone {file} {duration} disabled={busy} onfile={pick} />
            <p class="faint consent">
              <Icon name="info" size={16} />
              Tracks are processed, then deleted from the server after 30 minutes. Use audio you own or may use.
            </p>
          </div>
        </section>

        <section class="card" aria-labelledby="sound-title">
          <h2 id="sound-title" class="section-title">Sound</h2>
          <div class="stack">
            {#if profiles.length}
              <SoundControls
                {profiles}
                {modes}
                {duration}
                bind:mode
                bind:profile
                bind:beta
                bind:start
                bind:seconds
                disabled={busy}
              />
            {:else}
              <p class="faint">The settings appear once the backend is connected, because the profile list comes from it.</p>
            {/if}
          </div>
        </section>

        <div class="cta">
          <button type="button" class="btn btn-primary go" disabled={!file || status !== "online" || busy} onclick={render}>
            <Icon name="wave" size={20} />
            {report ? "Render again with these settings" : "Render"}
          </button>
          {#if !file}<p class="faint">Choose a track first.</p>
          {:else if status !== "online"}<p class="faint">Connect a backend first.</p>{/if}
        </div>
      </div>

      <div class="col">
        {#if error}
          <div class="notice error rise" role="alert">
            <Icon name="alert" size={20} />
            <div>
              <strong>That did not work.</strong>
              <p>{error}</p>
            </div>
          </div>
        {/if}

        {#if phase !== "idle"}
          <ProgressPanel {phase} {upload} {stages} {mode} oncancel={() => abort?.abort()} />
        {/if}

        {#if player && report && channels}
          {#key player}
            <Player {player} {report} {channels} trackName={resultName} />
          {/key}
          <RunReport {report} {notes} />
        {:else if !busy}
          <section class="card empty">
            <span class="empty-icon" aria-hidden="true"><Icon name="headphones" size={28} /></span>
            <h2 class="section-title">Nothing rendered yet</h2>
            <p class="faint">Your original and spatial versions will appear here, ready to compare. Nothing plays until a real render arrives.</p>
          </section>
        {/if}
      </div>
    </div>
  </main>

  <footer>
    <p class="faint">
      SoundStage is an independent research and engineering project. It is not affiliated with, or endorsed by, Spotify, Apple or Dolby.
      No perceptual claim is made yet: the blind tests decide.
    </p>
  </footer>
</div>

<BackendSettings bind:this={settings} url={backend} {status} {diagnosis} onsave={saveBackend} oncheck={check} />

<style>
  .shell {
    max-width: 1120px;
    margin: 0 auto;
    padding: 0 var(--gutter) calc(32px + env(safe-area-inset-bottom));
  }
  .top {
    position: sticky;
    top: 0;
    z-index: 10;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: calc(12px + env(safe-area-inset-top)) 0 12px;
    background: linear-gradient(var(--bg) 70%, transparent);
  }
  .brand {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    color: var(--text);
    text-decoration: none;
    font-weight: 800;
    font-size: 19px;
    letter-spacing: -0.02em;
  }
  .pill {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 40px;
    padding: 0 12px 0 14px;
    border-radius: 999px;
    border: 1px solid var(--line-strong);
    background: var(--surface);
    color: var(--text-2);
    font-size: 14px;
    font-weight: 600;
  }
  .led {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--text-3);
  }
  .led.online {
    background: var(--ok);
    box-shadow: 0 0 0 4px rgba(159, 216, 180, 0.15);
  }
  .led.offline {
    background: var(--danger);
  }
  .led.checking {
    background: var(--accent);
    animation: pulse 1.2s ease-in-out infinite;
  }
  @keyframes pulse {
    50% {
      opacity: 0.3;
    }
  }
  .hero {
    display: grid;
    gap: 10px;
    padding: 28px 0 28px;
  }
  h1 {
    font-size: clamp(34px, 9vw, 60px);
    line-height: 1.02;
    font-weight: 850;
    letter-spacing: -0.035em;
    max-width: 14ch;
  }
  .lede {
    max-width: 56ch;
    color: var(--text-2);
    font-size: 17px;
  }
  .grid {
    display: grid;
    gap: 16px;
  }
  .col {
    display: grid;
    gap: 16px;
    align-content: start;
    min-width: 0;
  }
  .stack {
    display: grid;
    gap: 14px;
    margin-top: 16px;
  }
  .consent {
    display: flex;
    gap: 8px;
    align-items: flex-start;
  }
  .consent :global(svg) {
    flex: none;
    margin-top: 3px;
  }
  .cta {
    position: sticky;
    bottom: 0;
    z-index: 5;
    display: grid;
    gap: 6px;
    justify-items: center;
    padding: 12px 0 calc(12px + env(safe-area-inset-bottom));
    background: linear-gradient(transparent, var(--bg) 35%);
  }
  .go {
    width: 100%;
    min-height: 56px;
    font-size: 17px;
  }
  .diag {
    display: grid;
    gap: 6px;
    min-width: 0;
  }
  .diag p {
    color: var(--text-2);
  }
  .diag ol {
    margin: 0;
    padding-left: 18px;
    display: grid;
    gap: 4px;
    word-break: break-word;
  }
  .diag-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 6px;
  }
  .notice p {
    word-break: break-word;
  }
  .empty {
    display: grid;
    justify-items: center;
    text-align: center;
    gap: 8px;
    padding: 40px 20px;
  }
  .empty-icon {
    display: grid;
    place-items: center;
    width: 64px;
    height: 64px;
    border-radius: 50%;
    background: var(--surface-2);
    color: var(--text-3);
    margin-bottom: 6px;
  }
  .empty .faint {
    max-width: 40ch;
  }
  footer {
    margin-top: 40px;
    padding-top: 20px;
    border-top: 1px solid var(--line);
  }
  @media (min-width: 960px) {
    .grid {
      grid-template-columns: minmax(0, 5fr) minmax(0, 6fr);
      gap: 24px;
      align-items: start;
    }
    .grid > .col:last-child {
      position: sticky;
      top: 76px;
    }
    .cta {
      position: static;
      background: none;
      padding: 0;
    }
  }
</style>
