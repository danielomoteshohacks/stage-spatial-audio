<script lang="ts">
  // The shell: four places (Home, Browse, Library, Create), a persistent mini player and a
  // full-screen player. This file owns the playback and job state; the screens are plain
  // components that receive data and callbacks.
  import { onDestroy, onMount } from "svelte";
  import Browse from "./components/Browse.svelte";
  import Create from "./components/Create.svelte";
  import Credits from "./components/Credits.svelte";
  import Home from "./components/Home.svelte";
  import seedCatalogue from "./data/catalogue.json";
  import Library from "./components/Library.svelte";
  import MiniPlayer from "./components/MiniPlayer.svelte";
  import Sheet from "./components/Sheet.svelte";
  import TabBar, { type Tab } from "./components/TabBar.svelte";
  import { BackendError, fetchArrayBuffer, uploadFile } from "./lib/api";
  import { readTags, artworkUrl as makeArtworkUrl } from "./lib/artwork";
  import { loadHead } from "./lib/calibration";
  import { HapticFeel, canVibrate, lowOnsets } from "./lib/haptics";
  import { fromLibrary, fromTrack, type Item } from "./lib/items";
  import { getEntry, listRecent, removeEntry, saveEntry, type LibrarySummary } from "./lib/library";
  import { setMediaSession, setPlaybackState } from "./lib/media";
  import type { Plan3 } from "./lib/scene3";
  import { loadBackendUrl, saveBackendUrl } from "./lib/settings";
  import { StreamPlayer, trimBuffer, type Side } from "./lib/stream";
  import { initTheme, loadChoice, saveChoice, type ThemeChoice } from "./lib/theme";
  import {
    catalog, jobs, optionsJson, pickFormat, streamJob,
    type JobOptions, type JobState, type Shelf,
  } from "./lib/v3";
  import type { Condition } from "./lib/blindtest";

  let backend = $state(loadBackendUrl());
  let status: "checking" | "online" | "offline" = $state("checking");
  // Full from the first render (see loadSeedShelves), replaced by the server's shelves when it answers.
  let shelves: Shelf[] = $state((seedCatalogue as { shelves: Shelf[] }).shelves);
  let formats: string[] = $state(["opus", "flac"]);
  let tab: Tab = $state("home");
  let browseGenre = $state("");
  let theme: ThemeChoice = $state(loadChoice());
  let stopTheme = () => {};

  let recents: LibrarySummary[] = $state([]);
  let sizes: Record<string, number> = $state({});
  let head = $state(loadHead());

  // Playback.
  let current: Item | null = $state(null);
  let queue: Item[] = $state([]);
  let index = $state(0);
  let player: StreamPlayer | null = $state(null);
  let playing = $state(false);
  let buffering = $state(false);
  let side: Side = $state("spatial");
  let time = $state(0);
  let duration = $state(0);
  let readyUntil = $state(0);
  let job: JobState | null = $state(null);
  let uploading: number | null = $state(null);
  let error: string | null = $state(null);
  let plan: Plan3 | null = $state(null);
  let guard: { verdict: "pass" | "review" | "fail"; reasons: string[]; coverage?: { analysed_s: number; song_s: number; full: boolean } | null } | null = $state(null);
  let downloads: { label: string; url: string; file: string }[] = $state([]);
  let feel = $state(false);
  let sheet: "none" | "player" | "calibrate" | "test" = $state("none");
  let creditsOpen = $state(false);
  let Player: typeof import("./components/NowPlaying.svelte").default | null = $state(null);
  let CalibrationC: typeof import("./components/Calibration.svelte").default | null = $state(null);
  let BlindTest: typeof import("./components/BlindTest.svelte").default | null = $state(null);
  let conditions: Condition[] = $state([]);

  let ctx: AudioContext | null = $state(null);
  let abort: AbortController | null = null;
  let raf = 0;
  let haptic: HapticFeel | null = null;
  let originalBuf: AudioBuffer | null = null;
  let originalBlob: Blob | null = null;
  // eslint-disable-next-line svelte/prefer-svelte-reactivity -- bookkeeping, never rendered
  let fetched = new Set<number>();
  let pumping = false;
  let runToken = 0;

  function audio(): AudioContext {
    ctx ??= new AudioContext({ latencyHint: "playback" });
    return ctx;
  }

  // The committed catalogue (src/data/catalogue.json, exported from the server's seed) is in the
  // bundle, so Home and Browse are full on the first paint: nothing waits for the server and
  // nothing jumps when it answers. When the server answers, its own shelves replace these.
  function loadSeedShelves() {
    if (!shelves.length) shelves = (seedCatalogue as { shelves: typeof shelves }).shelves;
  }

  async function check() {
    status = "checking";
    loadSeedShelves();
    // A sleeping Space takes up to a minute or two to wake, and answers the first requests slowly
    // or with an error, so one failed request is not "offline". Try for about two minutes.
    const waits = [0, 3000, 5000, 8000, 12000, 15000, 20000, 25000, 30000];
    for (const w of waits) {
      if (w) await new Promise((r) => setTimeout(r, w));
      try {
        const h = await jobs.health(backend);
        formats = h.formats;
        status = "online";
        try {
          const s = await catalog.shelves(backend);
          if (s.shelves.length) shelves = s.shelves;
        } catch {
          // Keep the committed shelves.
        }
        return;
      } catch {
        // Not awake yet; wait and ask again.
      }
    }
    status = "offline";
  }

  async function refreshLibrary() {
    recents = await listRecent();
  }

  const libItems = $derived(
    recents.map((e) => {
      const t = (e.run as { track?: import("./lib/v3").Track } | null)?.track;
      return t ? { ...fromTrack(t), id: `upload:${e.id}`, artId: t.id, kind: "upload" as const, libraryId: e.id } : fromLibrary(e);
    }),
  );

  // --- Opening a track ----------------------------------------------------------------------

  function reset() {
    abort?.abort();
    abort = null;
    runToken++;
    cancelAnimationFrame(raf);
    player?.dispose();
    player = null;
    playing = buffering = false;
    time = duration = readyUntil = 0;
    job = null;
    uploading = null;
    error = null;
    plan = null;
    guard = null;
    downloads = [];
    conditions = [];
    originalBuf = null;
    originalBlob = null;
    fetched = new Set();
    haptic = null;
  }

  function attach(buf: AudioBuffer) {
    const p = new StreamPlayer(audio(), buf);
    p.setSide(side);
    p.onended = () => {
      playing = false;
      if (index < queue.length - 1) void open(index + 1);
    };
    p.onbuffering = (b) => (buffering = b);
    player = p;
    originalBuf = buf;
    duration = buf.duration;
    if (canVibrate()) {
      haptic = new HapticFeel(lowOnsets(buf.getChannelData(0), buf.sampleRate));
      haptic.enabled = feel;
    }
    loop();
  }

  function loop() {
    cancelAnimationFrame(raf);
    const step = () => {
      if (player) {
        time = player.currentTime;
        readyUntil = player.readyUntil;
        playing = player.isPlaying;
        haptic?.tick(time);
        setPlaybackState(playing, time, duration);
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
  }

  async function decodeInto(buf: ArrayBuffer): Promise<AudioBuffer> {
    return await audio().decodeAudioData(buf.slice(0));
  }

  /** Fetch, decode, trim and hand over every segment the job has announced, in order. */
  async function pump(state: JobState, token: number) {
    if (pumping) return;
    pumping = true;
    try {
      for (const seg of state.segments ?? []) {
        if (token !== runToken || fetched.has(seg.index) || !state.id) continue;
        if (!player) return; // wait until the original is decoded; the next snapshot retries
        fetched.add(seg.index);
        const data = await fetchArrayBuffer(jobs.segmentUrl(backend, state.id, seg.file), abort?.signal);
        const dec = await decodeInto(data);
        if (token !== runToken) return;
        player.addSegment(seg.index, trimBuffer(audio(), dec, seg));
        if (seg.index === 0) {
          side = "spatial";
          void player.play();
        }
      }
    } catch (e) {
      if (!(e instanceof BackendError && e.kind === "cancelled")) error = "A part of the render could not be fetched.";
    } finally {
      pumping = false;
    }
  }

  function onState(s: JobState, token: number) {
    if (token !== runToken) return;
    job = s;
    if (s.plan) plan = s.plan as Plan3;
    if (s.error) error = s.error;
    void pump(s, token);
    if (s.done && s.status === "done") void finish(s, token);
  }

  async function finish(s: JobState, token: number) {
    let spatialFlac: Blob | null = null;
    // Wait for the last segments, then keep the whole render on this device.
    for (let i = 0; i < 100 && pumping; i++) await new Promise((r) => setTimeout(r, 100));
    await pump(s, token);
    if (token !== runToken || !s.id) return;
    player?.setComplete();
    guard = s.guard ? { ...s.guard, coverage: (s as { coverage?: never }).coverage ?? null } : null;
    downloads = [
      { label: "FLAC", url: jobs.fileUrl(backend, s.id, "spatial.flac"), file: `${current?.title ?? "song"}-spatial.flac` },
      { label: "Plan", url: jobs.fileUrl(backend, s.id, "plan.json"), file: "plan.json" },
    ];
    try {
      const rep = await fetch(jobs.fileUrl(backend, s.id, "report.json")).then((r) => r.json());
      guard = { verdict: rep.verdict, reasons: rep.reasons, coverage: rep.coverage ?? null };
      const flac = await fetch(jobs.fileUrl(backend, s.id, "spatial.flac")).then((r) => r.blob());
      spatialFlac = flac;
      if (originalBlob && current) {
        await saveEntry({
          id: crypto.randomUUID(), name: current.title, title: current.title, artist: current.artist,
          createdAt: Date.now(), original: originalBlob, spatial: flac, objects: {},
          // Plain copies: state proxies cannot be stored in IndexedDB.
          run: JSON.parse(JSON.stringify({ track: current.track ?? null, run: s.run ?? null })),
          report: rep, plan: s.plan, trackId: s.id, space: "dry_stage", durationS: duration,
        });
        await refreshLibrary();
      }
    } catch {
      // Saving is a convenience: the song keeps playing without it.
    }
    // The listening test compares the original with the whole spatial render, decoded from the
    // FLAC kept above. If that fails there is nothing to compare, and the test says so.
    try {
      if (originalBuf && spatialFlac) {
        const full = await decodeInto(await spatialFlac.arrayBuffer());
        if (token === runToken) {
          conditions = [{ id: "original", label: "Original", buffer: originalBuf }, { id: "v3", label: "SoundStage v3", buffer: full }];
        }
      }
    } catch {
      conditions = [];
    }
  }

  async function open(i: number, items: Item[] = queue) {
    const it = items[i];
    if (!it) return;
    audio();
    void ctx?.resume();
    reset();
    queue = items;
    index = i;
    current = it;
    sheet = "player";
    Player ??= (await import("./components/NowPlaying.svelte")).default;
    const token = runToken;
    const ac = new AbortController();
    abort = ac;
    try {
      if (it.kind === "upload" && it.libraryId) {
        const e = await getEntry(it.libraryId);
        if (!e) throw new Error("That saved render is gone from this device.");
        const [o, s] = await Promise.all([decodeInto(await e.original.arrayBuffer()), decodeInto(await e.spatial.arrayBuffer())]);
        if (token !== runToken) return;
        originalBlob = e.original;
        attach(o);
        player?.addSegment(0, s);
        player?.setComplete();
        plan = e.plan as Plan3;
        const rep = e.report as { verdict: "pass" | "review" | "fail"; reasons: string[] } | null;
        guard = rep ? { verdict: rep.verdict, reasons: rep.reasons } : null;
        conditions = [{ id: "original", label: "Original", buffer: o }, { id: "v3", label: "SoundStage v3", buffer: s }];
        void player?.play();
        return;
      }
      const track = it.track!;
      if (status !== "online") {
        // Without the server there is no spatial render, but the original can still play: fetch
        // it from its own host (the CC licence allows streaming it) and say plainly what this is.
        const data = await fetchArrayBuffer(track.audio_url, ac.signal).catch(() => {
          throw new Error("The server is asleep and this track's host refused a direct stream. Try again in a minute.");
        });
        originalBlob = new Blob([data], { type: "audio/mpeg" });
        const buf = await decodeInto(data);
        if (token !== runToken) return;
        attach(buf);
        error = "Playing the original. The spatial version needs the server, which is waking up.";
        void player?.play();
        return;
      }
      const fmt = pickFormat(formats);
      const opts: JobOptions = { preset: "fast", head, fmt };
      const origPromise = fetchArrayBuffer(catalog.audioUrl(backend, track.id), ac.signal).then(async (data) => {
        originalBlob = new Blob([data], { type: "audio/mpeg" });
        const buf = await decodeInto(data);
        if (token === runToken) {
          attach(buf);
          if (job) void pump(job, token);
        }
      });
      const jobPromise = streamJob(backend, "v3_catalog", [track.id, optionsJson(opts)], (s) => onState(s, token), ac.signal);
      await Promise.all([origPromise, jobPromise]);
    } catch (e) {
      if (token === runToken && !(e instanceof BackendError && e.kind === "cancelled")) {
        error = e instanceof Error ? e.message : "That did not work.";
      }
    }
  }

  async function startUpload(file: File, o: JobOptions) {
    audio();
    void ctx?.resume();
    reset();
    const token = runToken;
    const ac = new AbortController();
    abort = ac;
    const tags = await readTags(file).catch(() => ({ title: "", artist: "", artwork: undefined }));
    const art = makeArtworkUrl(tags.artwork) ?? "";
    current = { id: `local:${file.name}:${file.size}`, title: tags.title || file.name.replace(/\.[^.]+$/, ""), artist: tags.artist || "Your upload", artworkUrl: art, durationS: 0, kind: "upload" };
    queue = [current];
    index = 0;
    originalBlob = file;
    Player ??= (await import("./components/NowPlaying.svelte")).default;
    try {
      const decoded = decodeInto(await file.arrayBuffer()).then((buf) => {
        if (token === runToken) {
          attach(buf);
          if (job) void pump(job, token);
        }
      });
      uploading = 0;
      const path = await uploadFile(backend, file, (f) => (uploading = f), ac.signal);
      uploading = null;
      const opts = { ...o, fmt: pickFormat(formats) };
      const data = [{ path, orig_name: file.name, meta: { _type: "gradio.FileData" } }, optionsJson(opts)];
      let opened = false;
      await Promise.all([decoded, streamJob(backend, "v3_process", data, (s) => {
        onState(s, token);
        if (!opened && (s.segments?.length ?? 0) > 0) {
          opened = true;
          sheet = "player";
        }
      }, ac.signal)]);
    } catch (e) {
      uploading = null;
      if (token === runToken && !(e instanceof BackendError && e.kind === "cancelled")) {
        error = e instanceof Error ? e.message : "That did not work.";
      }
    }
  }

  function cancelJob() {
    reset();
    current = null;
  }

  // --- Controls -----------------------------------------------------------------------------

  async function toggle() {
    if (!player) return;
    if (player.isPlaying) player.pause();
    else await player.play();
    playing = player.isPlaying;
  }
  async function seek(t: number) {
    await player?.seek(t);
    haptic?.reset(t);
    time = t;
  }
  function setSide(s: Side) {
    side = s;
    player?.setSide(s);
  }
  function setFeel() {
    feel = !feel;
    if (haptic) {
      haptic.enabled = feel;
      haptic.reset(time);
    }
  }

  function cycleTheme() {
    theme = theme === "system" ? "light" : theme === "light" ? "dark" : "system";
    setTheme(theme);
  }
  function setTheme(t: ThemeChoice) {
    theme = t;
    saveChoice(t);
    stopTheme();
    stopTheme = initTheme(t);
  }

  async function removeItem(it: Item) {
    if (!it.libraryId) return;
    await removeEntry(it.libraryId);
    await refreshLibrary();
  }

  async function openCalibration() {
    CalibrationC ??= (await import("./components/Calibration.svelte")).default;
    sheet = "calibrate";
  }
  async function openTest() {
    BlindTest ??= (await import("./components/BlindTest.svelte")).default;
    sheet = "test";
  }

  function onKey(e: KeyboardEvent) {
    const el = e.target as HTMLElement | null;
    if (!current || el?.closest("input, textarea, select, [contenteditable]")) return;
    if (e.code === "Space" && !el?.closest("button, a")) {
      e.preventDefault();
      void toggle();
    } else if (e.key === "ArrowRight") void seek(Math.min(duration, time + 5));
    else if (e.key === "ArrowLeft") void seek(Math.max(0, time - 5));
    else if (e.key.toLowerCase() === "o") setSide(side === "spatial" ? "original" : "spatial");
  }

  $effect(() => {
    if (!current) return;
    setMediaSession(
      { title: current.title, artist: current.artist, artworkUrl: current.artworkUrl || null },
      { play: () => void toggle(), pause: () => void toggle(), seek: (t) => void seek(t), position: () => ({ t: time, duration }) },
    );
  });

  onMount(() => {
    stopTheme = initTheme(theme);
    void check();
    void refreshLibrary();
  });
  onDestroy(() => {
    stopTheme();
    cancelAnimationFrame(raf);
    player?.dispose();
  });

  const renderProgress = $derived.by(() => {
    const j = job as JobState | null;
    const p = player as StreamPlayer | null;
    return j?.chunks_total ? (j.chunks_done ?? 0) / j.chunks_total : p?.isComplete ? 1 : 0;
  });
  const spatialReady = $derived.by(() => {
    const p = player as StreamPlayer | null;
    return !!p && (p.isComplete || readyUntil >= time + 1);
  });
</script>

<svelte:window onkeydown={onKey} />
<a class="skip" href="#main">Skip to the content</a>

<TabBar {tab} {theme} onselect={(t) => { tab = t; browseGenre = ""; }} ontheme={cycleTheme} oncredits={() => (creditsOpen = true)} />

{#if tab === "home"}
  <Home
    recents={libItems.slice(0, 8)}
    {shelves}
    {status}
    onplay={(i, q) => open(Math.max(0, q.findIndex((x) => x.id === i.id)), q)}
    onbrowse={(g) => { browseGenre = g ?? ""; tab = "browse"; }}
    oncreate={() => (tab = "create")}
  />
{:else if tab === "browse"}
  <Browse {backend} {shelves} initial={browseGenre} onplay={(i, q) => open(Math.max(0, q.findIndex((x) => x.id === i.id)), q)} />
{:else if tab === "library"}
  <Library items={libItems} {sizes} onplay={(i, q) => open(Math.max(0, q.findIndex((x) => x.id === i.id)), q)} onremove={removeItem} oncreate={() => (tab = "create")} />
{:else}
  <Create {job} {uploading} {head} {error} onstart={startUpload} oncancel={cancelJob} oncalibrate={openCalibration} />
{/if}

{#if current && sheet !== "player"}
  <MiniPlayer item={current} {playing} busy={buffering || (!player && !error)} {side} {time} {duration} onopen={() => (sheet = "player")} ontoggle={toggle} />
{/if}

<!-- A sheet closed from code fires its close event too; only act when it is still the one showing. -->
<Sheet open={sheet === "player"} title="Now playing" full bare onclose={() => sheet === "player" && (sheet = "none")}>
  {#if current && Player}
    <Player
      item={current} {queue} {index} {playing} busy={!player && !error} {buffering} {time} {duration} {readyUntil}
      {renderProgress} {spatialReady} {side} {plan} {guard} {feel} canFeel={canVibrate()} {downloads}
      onclose={() => (sheet = "none")} ontoggle={toggle} onseek={seek} onside={setSide}
      onprev={() => open(index - 1)} onnext={() => open(index + 1)} onpick={(i) => open(i)}
      onfeel={setFeel} oncalibrate={openCalibration}
    />
    {#if error}<p role="alert" class="err">{error}</p>{/if}
  {/if}
</Sheet>

<Sheet open={sheet === "calibrate"} title="Fit to my ears" onclose={() => sheet === "calibrate" && (sheet = current ? "player" : "none")}>
  {#if CalibrationC}
    <CalibrationC {backend} ondone={(h) => { head = h; sheet = current ? "player" : "none"; }} onclose={() => (sheet = current ? "player" : "none")} />
  {/if}
</Sheet>

<Sheet open={sheet === "test"} title="Listening test" onclose={() => sheet === "test" && (sheet = "none")}>
  {#if BlindTest && conditions.length > 1 && ctx && current}
    <BlindTest {ctx} track={current.title} {conditions} />
  {:else}
    <p class="muted">Play a song to the end of its render first: the test compares what you just heard.</p>
  {/if}
</Sheet>

<Sheet open={creditsOpen} title="Credits and settings" onclose={() => (creditsOpen = false)}>
  <Credits {backend} {theme} onbackend={(u) => { backend = saveBackendUrl(u); void check(); }} ontheme={setTheme} ontest={openTest} />
</Sheet>

<style>
  .skip {
    position: fixed;
    left: var(--gap-3);
    top: -60px;
    z-index: 100;
    padding: var(--gap-2) var(--gap-4);
    border-radius: var(--radius-pill);
    background: var(--surface);
    box-shadow: var(--shadow-2);
    transition: top var(--dur-2) var(--ease);
  }
  .skip:focus {
    top: var(--gap-3);
  }
  .err {
    color: var(--fail);
    font-weight: 600;
    padding: 0 var(--gap-5);
  }
</style>
