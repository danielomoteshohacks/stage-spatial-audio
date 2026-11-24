<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import About from "./components/About.svelte";
  import DropZone from "./components/DropZone.svelte";
  import Icon from "./components/Icon.svelte";
  import Logo from "./components/Logo.svelte";
  import NowPlaying from "./components/NowPlaying.svelte";
  import ProgressPanel from "./components/ProgressPanel.svelte";
  import Sheet from "./components/Sheet.svelte";
  import {
    BackendError,
    checkBackend,
    diagnose,
    fetchArrayBuffer,
    fileUrl,
    runProcess,
    runRerender,
    uploadFile,
    type Diagnosis,
    type GuardReport,
    type ProcessOutput,
    type ProcessRequest,
    type StageState,
  } from "./lib/api";
  import { artworkUrl as makeArtworkUrl, readTags } from "./lib/artwork";
  import type { Condition } from "./lib/blindtest";
  import { SyncPlayer, type Side } from "./lib/engine";
  import { levelEnvelope } from "./lib/format";
  import { HapticFeel, lowOnsets } from "./lib/haptics";
  import { GENRES, SPACE_INFO, type Character, type SpaceName } from "./lib/labels";
  import { getEntry, listRecent, removeEntry, saveEntry, type LibraryEntry, type LibrarySummary } from "./lib/library";
  import { setMediaSession, setPlaybackState } from "./lib/media";
  import type { Plan } from "./lib/scene";
  import { loadBackendUrl, saveBackendUrl } from "./lib/settings";

  /** The server keeps a track's cache for 30 minutes after its last render. */
  const SERVER_TTL_MS = 28 * 60 * 1000;
  const UPLOAD_REUSE_MS = 20 * 60 * 1000;

  let backend = $state(loadBackendUrl());
  let backendDraft = $state(loadBackendUrl());
  let status: "checking" | "online" | "offline" = $state("checking");
  let diagnosis: Diagnosis | null = $state(null);

  let file: File | null = $state(null);
  let quick = $state(false);
  let space: SpaceName = $state("studio");
  let character: Character = $state("balanced");
  let motion = $state(0.5);
  let genre = $state("auto");
  let applied = $state({ space: "studio", character: "balanced", motion: 0.5, genre: "auto" });

  let phase: "idle" | "uploading" | "processing" | "downloading" = $state("idle");
  let upload = $state(0);
  let stages: StageState[] = $state([]);
  let error: string | null = $state(null);

  let player: SyncPlayer | null = $state(null);
  let channels: Float32Array[] = $state([]);
  let title = $state("");
  let artist: string | undefined = $state(undefined);
  let artworkUrl: string | null = $state(null);
  let artworkBlob: Blob | undefined = undefined;
  let report: GuardReport | null = $state(null);
  let plan: Plan | null = $state(null);
  let editedPlan: Plan | null = $state(null);
  let trackId: string | null = $state(null);
  let renderedAt = $state(0);
  let detectedGenre: string | null = $state(null);
  let downloads: { label: string; url: string; file: string }[] = $state([]);
  let levels: Record<string, Float32Array> = $state({});
  let time = $state(0);
  let playing = $state(false);
  let side: Side = $state("spatial");
  let feel = $state(false);
  let feelIntensity = $state(0.6);
  let haptic: HapticFeel | null = null;

  let sheet: "none" | "player" | "about" | "settings" | "test" = $state("none");
  let recents: LibrarySummary[] = $state([]);
  let BlindTest: typeof import("./components/BlindTest.svelte").default | null = $state(null);
  let conditions: Condition[] = $state([]);
  let addingV1 = $state(false);

  let abort: AbortController | null = null;
  let uploaded: { file: File; path: string; at: number; backend: string } | null = null;
  let ctx: AudioContext | null = null;
  let raf = 0;

  let busy = $derived(phase !== "idle");
  let dirty = $derived(
    applied.space !== space || applied.character !== character || Math.abs(applied.motion - motion) > 1e-6 || applied.genre !== genre,
  );
  const online = (): boolean => status === "online";
  let canRerender = $derived(!!trackId && Date.now() - renderedAt < SERVER_TTL_MS && online());

  function audio(): AudioContext {
    ctx ??= new AudioContext({ latencyHint: "playback" });
    return ctx;
  }

  async function check() {
    status = "checking";
    diagnosis = null;
    try {
      await checkBackend(backend);
      status = "online";
    } catch (e) {
      status = "offline";
      diagnosis =
        e instanceof BackendError && e.kind === "protocol"
          ? { title: "That address is not a SoundStage server", detail: e.message, fixes: ["Check the address in Settings."] }
          : diagnose(backend, window.location);
    }
  }

  function request(extra: Partial<ProcessRequest> = {}): ProcessRequest {
    return {
      mode: quick ? "lite" : "stems",
      profile: `space:${space}`,
      beta: 2.0,
      start: null,
      seconds: 30,
      genre,
      motion,
      character,
      ...extra,
    };
  }

  async function pick(f: File) {
    file = f;
    error = null;
    const tags = await readTags(f);
    title = tags.title || f.name.replace(/\.[^.]+$/, "");
    artist = tags.artist;
    if (artworkUrl) URL.revokeObjectURL(artworkUrl);
    artworkUrl = makeArtworkUrl(tags.artwork);
    artworkBlob = tags.artwork ? new Blob([new Uint8Array(tags.artwork.bytes).buffer], { type: tags.artwork.mime }) : undefined;
    await render();
  }

  async function render(extra: Partial<ProcessRequest> = {}, viaCache = false) {
    if (status !== "online") {
      error = "The server is not reachable. Open Settings to check its address.";
      return;
    }
    error = null;
    abort = new AbortController();
    const signal = abort.signal;
    const ac = audio();
    void ac.resume().catch(() => undefined);
    const req = request(extra);
    try {
      let out: ProcessOutput;
      phase = "processing";
      stages = [];
      if (viaCache && trackId) {
        out = await runRerender(backend, trackId, req, (o) => o[0]?.stages && (stages = o[0].stages), signal);
      } else {
        if (!file) return;
        let path: string;
        if (uploaded && uploaded.file === file && uploaded.backend === backend && Date.now() - uploaded.at < UPLOAD_REUSE_MS) {
          path = uploaded.path;
        } else {
          phase = "uploading";
          upload = 0;
          path = await uploadFile(backend, file, (fr) => (upload = fr), signal);
          uploaded = { file, path, at: Date.now(), backend };
          phase = "processing";
        }
        out = await runProcess(backend, path, file.name, req, (o) => o[0]?.stages && (stages = o[0].stages), signal);
      }
      const [progress, original, spatial, stems] = out;
      if (progress.error || !original || !spatial) throw new BackendError(progress.error ?? "The server sent no audio.", "server");
      phase = "downloading";
      const files = [original, spatial, ...(stems ?? [])];
      const blobs = await Promise.all(files.map(async (fd) => new Blob([await fetchArrayBuffer(fileUrl(backend, fd), signal)], { type: "audio/flac" })));
      const names = (stems ?? []).map((fd) => fd.path.split("/").pop()!.replace(/\.flac$/, ""));
      const objects = Object.fromEntries(names.map((n, i) => [n, blobs[2 + i]]));
      report = progress.report ?? null;
      plan = (progress.plan as Plan) ?? null;
      editedPlan = null;
      trackId = progress.track_id ?? null;
      renderedAt = Date.now();
      const g = progress.run as unknown as { analysis?: { genre?: { genre?: string | null } } } | undefined;
      const gid = g?.analysis?.genre?.genre ?? null;
      detectedGenre = gid ? (GENRES.find((x) => x.id === gid)?.label ?? gid) : null;
      downloads = [
        { label: "Spatial FLAC", url: URL.createObjectURL(blobs[1]), file: `${title} (SoundStage).flac` },
        ...(progress.files?.plan ? [{ label: "plan.json", url: fileUrl(backend, { path: progress.files.plan }), file: "plan.json" }] : []),
        ...(progress.files?.bed_7_1_4 ? [{ label: "7.1.4 WAV", url: fileUrl(backend, { path: progress.files.bed_7_1_4 }), file: "bed_7_1_4.wav" }] : []),
      ];
      applied = { space, character, motion, genre };
      await load(blobs[0], blobs[1], objects);
      const entry: LibraryEntry = {
        id: `${trackId ?? "local"}-${space}-${character}-${motion}-${genre}`,
        name: file?.name ?? title,
        title,
        artist,
        createdAt: Date.now(),
        original: blobs[0],
        spatial: blobs[1],
        objects,
        artwork: artworkBlob,
        run: progress.run,
        report,
        plan,
        trackId,
        space,
        durationS: player?.duration ?? 0,
      };
      void saveEntry(entry).then(refreshRecents);
      sheet = "player";
    } catch (e) {
      if (!(e instanceof BackendError && e.kind === "cancelled")) error = e instanceof Error ? e.message : String(e);
    } finally {
      phase = "idle";
      abort = null;
    }
  }

  async function load(original: Blob, spatial: Blob, objects: Record<string, Blob>, keepTime = true) {
    const ac = audio();
    const at = keepTime && player ? player.currentTime : 0;
    const wasPlaying = keepTime && playing;
    const [ob, sb, ...stemBufs] = await Promise.all([original, spatial, ...Object.values(objects)].map(async (b) => ac.decodeAudioData(await b.arrayBuffer())));
    const stemMap = Object.fromEntries(Object.keys(objects).map((k, i) => [k, stemBufs[i]]));
    player?.dispose();
    player = new SyncPlayer(ac, { original: ob, spatial: sb, stems: stemMap });
    player.onended = () => (playing = false);
    player.setSide(side);
    channels = Array.from({ length: ob.numberOfChannels }, (_, i) => ob.getChannelData(i));
    levels = Object.fromEntries(Object.entries(stemMap).map(([k, b]) => [k, levelEnvelope(b)]));
    const low = stemMap["low_end"] ?? ob;
    haptic = new HapticFeel(lowOnsets(low.getChannelData(0), low.sampleRate));
    conditions = [
      { id: "original", label: "Original", buffer: ob },
      { id: "v2", label: "SoundStage v2", buffer: sb },
    ];
    await applyPalette();
    setMediaSession({ title, artist, artworkUrl }, {
      play: () => void playPause(true),
      pause: () => void playPause(false),
      seek: (t) => void player?.seek(t),
      position: () => ({ t: player?.currentTime ?? 0, duration: player?.duration ?? 0 }),
    });
    if (at > 0) await player.seek(at);
    if (wasPlaying) await playPause(true);
  }

  async function applyPalette() {
    const root = document.documentElement.style;
    if (!artworkUrl) {
      root.removeProperty("--accent");
      root.removeProperty("--accent-2");
      return;
    }
    try {
      const { extractPalette } = await import("./lib/palette");
      const p = await extractPalette(artworkUrl);
      if (p) {
        root.setProperty("--accent", p.accent);
        root.setProperty("--accent-2", p.accent2);
      }
    } catch {
      // A broken image keeps the brand colours.
    }
  }

  async function playPause(force?: boolean) {
    if (!player) return;
    const want = force ?? !playing;
    if (want) {
      await player.play();
      haptic?.reset(player.currentTime);
    } else player.pause();
    playing = player.isPlaying;
    setPlaybackState(playing, player.currentTime, player.duration);
  }

  function setSide(s: Side) {
    side = s;
    player?.setSide(s);
  }

  function tick() {
    if (player) {
      const t = player.currentTime;
      if (t < time - 0.5) haptic?.reset(t);
      time = t;
      if (haptic) {
        haptic.enabled = feel && playing;
        haptic.intensity = feelIntensity;
        haptic.tick(t);
      }
    }
    raf = requestAnimationFrame(tick);
  }

  async function openRecent(id: string) {
    const e = await getEntry(id);
    if (!e) return refreshRecents();
    title = e.title ?? e.name;
    artist = e.artist;
    if (artworkUrl) URL.revokeObjectURL(artworkUrl);
    artworkUrl = e.artwork ? URL.createObjectURL(e.artwork) : null;
    artworkBlob = e.artwork;
    report = e.report as GuardReport | null;
    plan = e.plan as Plan | null;
    trackId = e.trackId;
    renderedAt = e.createdAt;
    space = (e.space as SpaceName) ?? "studio";
    applied = { space, character, motion, genre };
    downloads = [{ label: "Spatial FLAC", url: URL.createObjectURL(e.spatial), file: `${title} (SoundStage).flac` }];
    file = null;
    await load(e.original, e.spatial, e.objects, false);
    sheet = "player";
  }

  async function refreshRecents() {
    recents = await listRecent();
  }

  async function openTest() {
    sheet = "test";
    if (!BlindTest) BlindTest = (await import("./components/BlindTest.svelte")).default;
  }

  async function addV1() {
    if (!trackId || !player) return;
    addingV1 = true;
    try {
      const out = await runRerender(backend, trackId, { ...request(), mode: "lite", profile: "max" }, () => undefined);
      const fd = out[2];
      if (fd) {
        const buf = await audio().decodeAudioData(await fetchArrayBuffer(fileUrl(backend, fd)));
        conditions = [...conditions, { id: "v1", label: "SoundStage v1", buffer: buf }];
      }
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      addingV1 = false;
    }
  }

  function key(e: KeyboardEvent) {
    const target = e.target as HTMLElement;
    if (!player || ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName)) return;
    if (e.key === " " && target.tagName !== "BUTTON") {
      e.preventDefault();
      void playPause();
    } else if (e.key === "s" || e.key === "S") setSide(side === "spatial" ? "original" : "spatial");
    else if (e.key === "ArrowLeft" && target.tagName !== "CANVAS") void player.seek(Math.max(0, time - 5));
    else if (e.key === "ArrowRight" && target.tagName !== "CANVAS") void player.seek(Math.min(player.duration, time + 5));
    else if (e.key === "[") void player.setLoop({ start: time, end: player.loopRegion?.end ?? player.duration });
    else if (e.key === "]") void player.setLoop({ start: player.loopRegion?.start ?? 0, end: time });
    else if (e.key === "l" || e.key === "L") void player.setLoop(null);
  }

  onMount(() => {
    void check();
    void refreshRecents();
    raf = requestAnimationFrame(tick);
  });

  onDestroy(() => {
    cancelAnimationFrame(raf);
    player?.dispose();
  });
</script>

<svelte:window onkeydown={key} />

<main class="app">
  <header class="top">
    <a class="brand" href="/" aria-label="SoundStage home"><Logo size={30} /><span>SoundStage</span></a>
    <div class="top-actions">
      <span class={`status ${status}`} title={status === "online" ? "Server ready" : status === "checking" ? "Checking the server" : "Server not reachable"}>
        <span class="sr-only">Server {status}</span>
      </span>
      <button class="btn icon ghost" type="button" onclick={() => (sheet = "about")} aria-label="About SoundStage"><Icon name="info" /></button>
      <button class="btn icon ghost" type="button" onclick={() => (sheet = "settings")} aria-label="Settings"><Icon name="settings" /></button>
    </div>
  </header>

  <section class="hero">
    <p class="eyebrow">Spatial audio for any song, on any phone</p>
    <h1>Step inside<br />the record.</h1>
    <p class="muted lede">Drop a song you own. SoundStage builds a stage around you from its own parts, keeps the vocal and the bass where the artist put them, and checks the result against the original.</p>
  </section>

  {#if status === "offline" && diagnosis}
    <section class="notice glass" role="alert">
      <Icon name="alert" />
      <div>
        <p><strong>{diagnosis.title}</strong></p>
        <p class="muted small">{diagnosis.detail}</p>
        <ul class="small">
          {#each diagnosis.fixes as f (f)}<li>{f}</li>{/each}
        </ul>
        <button class="btn" type="button" onclick={check}><Icon name="refresh" size={16} /> Check again</button>
      </div>
    </section>
  {/if}

  {#if busy}
    <ProgressPanel phase={phase === "idle" ? "processing" : phase} {upload} {stages} oncancel={() => abort?.abort()} />
  {:else}
    <DropZone disabled={status !== "online"} onfile={pick} />
    <div class="options">
      <label class="check"><input type="checkbox" bind:checked={quick} /> Quick render <span class="faint">(no separation: faster, fewer parts)</span></label>
      <label class="space">Space
        <select bind:value={space}>
          {#each Object.entries(SPACE_INFO) as [id, info] (id)}<option value={id}>{info.label}</option>{/each}
        </select>
      </label>
    </div>
  {/if}

  {#if error}
    <p class="error" role="alert"><Icon name="alert" size={18} /> {error}</p>
  {/if}

  {#if recents.length}
    <section class="recents">
      <h2>On this phone</h2>
      <ul>
        {#each recents as r (r.id)}
          <li class="glass">
            <button class="recent" type="button" onclick={() => openRecent(r.id)}>
              <span class="thumb">{#if r.artwork}<img src={URL.createObjectURL(r.artwork)} alt="" />{:else}<Logo size={26} title="" />{/if}</span>
              <span class="meta">
                <span class="name">{r.title ?? r.name}</span>
                <span class="faint small">{SPACE_INFO[r.space as SpaceName]?.label ?? r.space} · {new Date(r.createdAt).toLocaleDateString()}</span>
              </span>
            </button>
            <button class="btn icon ghost" type="button" aria-label={`Remove ${r.title ?? r.name}`} onclick={() => removeEntry(r.id).then(refreshRecents)}><Icon name="trash" size={18} /></button>
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  <footer class="foot faint small">
    <p>Tracks are processed on the server and deleted after 30 minutes. Use music you own or may use.</p>
  </footer>
</main>

{#if player && sheet !== "player"}
  <button class="mini glass" type="button" onclick={() => (sheet = "player")} aria-label={`Open the player: ${title}`}>
    <span class="thumb">{#if artworkUrl}<img src={artworkUrl} alt="" />{:else}<Logo size={24} title="" />{/if}</span>
    <span class="name">{title}</span>
    <span class="side">{side === "spatial" ? "Spatial" : "Original"}</span>
    <span
      class="mini-play"
      role="button"
      tabindex="0"
      aria-label={playing ? "Pause" : "Play"}
      onclick={(e) => {
        e.stopPropagation();
        void playPause();
      }}
      onkeydown={(e) => {
        if (e.key === "Enter") {
          e.stopPropagation();
          void playPause();
        }
      }}><Icon name={playing ? "pause" : "play"} size={22} /></span>
  </button>
{/if}

<Sheet open={sheet === "player" && !!player} title={title || "Now playing"} full bare onclose={() => (sheet = "none")}>
  {#if player}
    <NowPlaying
      {player}
      {channels}
      {title}
      {artist}
      {artworkUrl}
      {report}
      plan={editedPlan ?? plan}
      {detectedGenre}
      {downloads}
      {levels}
      {time}
      {playing}
      {side}
      bind:space
      bind:character
      bind:motion
      bind:genre
      bind:feel
      bind:feelIntensity
      {dirty}
      {busy}
      {canRerender}
      onapply={() => render({}, true)}
      onplan={(p) => (editedPlan = p)}
      onrerenderplan={() => render({ plan: editedPlan ?? plan ?? undefined }, true)}
      onclose={() => (sheet = "none")}
      onplay={() => playPause()}
      onside={setSide}
      onblindtest={openTest}
    />
    {#if busy}<div class="overlay"><ProgressPanel phase={phase === "idle" ? "processing" : phase} {upload} {stages} oncancel={() => abort?.abort()} /></div>{/if}
  {/if}
</Sheet>

<Sheet open={sheet === "about"} title="Why SoundStage" onclose={() => (sheet = "none")}>
  <About />
</Sheet>

<Sheet open={sheet === "settings"} title="Settings" onclose={() => (sheet = "none")}>
  <form
    class="settings"
    onsubmit={(e) => {
      e.preventDefault();
      backend = saveBackendUrl(backendDraft);
      uploaded = null;
      void check();
    }}
  >
    <label class="field">
      <span class="field-label">Server address</span>
      <input class="input" type="url" bind:value={backendDraft} autocomplete="off" spellcheck="false" />
    </label>
    <p class="faint small">The SoundStage server that renders your tracks. Status: {status}.</p>
    <button class="btn primary" type="submit">Save and check</button>
  </form>
</Sheet>

<Sheet open={sheet === "test"} title="Blind test" onclose={() => (sheet = "player")}>
  {#if BlindTest && conditions.length && audio()}
    <BlindTest ctx={audio()} track={title} {conditions} onaddv1={canRerender ? addV1 : undefined} {addingV1} />
  {:else}
    <p class="muted">Render a track first; the test compares its versions.</p>
  {/if}
</Sheet>

<style>
  .app {
    max-width: 640px;
    margin: 0 auto;
    padding: max(var(--gap-4), env(safe-area-inset-top)) var(--gap-4) calc(120px + env(safe-area-inset-bottom));
    display: grid;
    gap: var(--gap-6);
  }

  .top {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .brand {
    display: inline-flex;
    align-items: center;
    gap: var(--gap-2);
    color: var(--ivory);
    text-decoration: none;
    font-weight: 600;
    letter-spacing: 0.01em;
  }

  .top-actions {
    display: flex;
    align-items: center;
    gap: 2px;
  }

  .status {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    margin-right: var(--gap-2);
    background: var(--ivory-3);
  }

  .status.online {
    background: var(--lagoon);
    box-shadow: 0 0 10px var(--lagoon);
  }

  .status.offline {
    background: var(--coral);
  }

  .hero {
    display: grid;
    gap: var(--gap-4);
    padding-top: var(--gap-5);
  }

  h1 {
    font-size: var(--text-hero);
  }

  .lede {
    font-size: var(--text-lg);
    line-height: 1.4;
    max-width: 34ch;
  }

  .options {
    display: grid;
    gap: var(--gap-3);
    font-size: var(--text-sm);
  }

  .check {
    display: flex;
    gap: var(--gap-2);
    align-items: center;
  }

  .check input {
    width: 20px;
    height: 20px;
    accent-color: var(--lagoon);
  }

  .space {
    display: grid;
    gap: 6px;
    color: var(--ivory-2);
  }

  .notice {
    display: flex;
    gap: var(--gap-3);
    padding: var(--gap-4);
    border-radius: var(--radius-md);
  }

  .notice ul {
    padding-left: 1.1em;
  }

  .error {
    display: flex;
    gap: var(--gap-2);
    align-items: flex-start;
    color: var(--coral);
  }

  .small {
    font-size: var(--text-xs);
  }

  .recents {
    display: grid;
    gap: var(--gap-3);
  }

  .recents h2 {
    font-size: var(--text-xl);
  }

  .recents ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--gap-2);
  }

  .recents li {
    display: flex;
    align-items: center;
    padding: var(--gap-2);
    border-radius: var(--radius-md);
  }

  .recent {
    flex: 1;
    display: flex;
    align-items: center;
    gap: var(--gap-3);
    border: 0;
    background: transparent;
    text-align: left;
    cursor: pointer;
    min-height: 56px;
  }

  .thumb {
    width: 48px;
    height: 48px;
    flex: none;
    border-radius: var(--radius-sm);
    overflow: hidden;
    display: grid;
    place-items: center;
    background: var(--ink-3);
  }

  .thumb img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .meta {
    display: grid;
    min-width: 0;
  }

  .name {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .foot {
    text-align: center;
  }

  .mini {
    position: fixed;
    left: var(--gap-3);
    right: var(--gap-3);
    bottom: calc(var(--gap-3) + env(safe-area-inset-bottom));
    z-index: 10;
    max-width: 616px;
    margin: 0 auto;
    display: flex;
    align-items: center;
    gap: var(--gap-3);
    padding: var(--gap-2);
    padding-right: var(--gap-3);
    border-radius: var(--radius-lg);
    cursor: pointer;
    text-align: left;
    animation: up var(--dur-3) var(--ease-out);
  }

  .mini .name {
    flex: 1;
    font-weight: 500;
  }

  .mini .side {
    font-size: var(--text-xs);
    color: var(--accent);
  }

  .mini-play {
    width: 44px;
    height: 44px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: var(--ivory);
    color: var(--ink);
  }

  .overlay {
    position: fixed;
    inset: auto var(--gap-4) var(--gap-4);
    z-index: 20;
  }

  .settings {
    display: grid;
    gap: var(--gap-4);
  }

  @keyframes up {
    from {
      transform: translateY(20px);
      opacity: 0;
    }
  }
</style>
