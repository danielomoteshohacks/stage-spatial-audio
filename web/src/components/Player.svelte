<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import type { RunReport } from "../lib/api";
  import { clampLoop, type LoopRegion, type Side, type StemMix, type SyncPlayer } from "../lib/engine";
  import { formatPrecise, formatTime } from "../lib/format";
  import { profileInfo, STEM_LABELS } from "../lib/labels";
  import Icon from "./Icon.svelte";
  import StemMixer from "./StemMixer.svelte";
  import Waveform from "./Waveform.svelte";

  let {
    player,
    report,
    channels,
    trackName,
  }: {
    player: SyncPlayer;
    report: RunReport;
    channels: { original: Float32Array[]; spatial: Float32Array[] };
    trackName: string;
  } = $props();

  let side = $state<Side>("spatial");
  let playing = $state(false);
  let time = $state(0);
  let loop = $state<LoopRegion | null>(null);
  let mix = $state<StemMix>({ solo: [], muted: [] });
  let custom = $state(false);
  let raf = 0;

  function tick() {
    time = player.currentTime;
    playing = player.isPlaying;
    if (playing) raf = requestAnimationFrame(tick);
  }

  async function playPause() {
    if (player.isPlaying) {
      player.pause();
      tick();
    } else {
      await player.play();
      cancelAnimationFrame(raf);
      tick();
    }
  }

  function choose(next: Side) {
    player.setSide(next);
    side = next;
  }

  function toggle() {
    side = player.toggle();
  }

  async function seek(t: number) {
    // A seek outside the loop means the listener has moved on from that passage.
    if (loop && (t < loop.start || t >= loop.end)) {
      await player.setLoop(null);
      loop = null;
    }
    await player.seek(t);
    tick();
  }

  async function setLoop(a: number, b: number) {
    const region = clampLoop(a, b, player.duration);
    await player.setLoop(region);
    loop = region;
    tick();
  }

  async function clearLoop() {
    await player.setLoop(null);
    loop = null;
    tick();
  }

  function setLoopEdge(edge: "start" | "end") {
    const t = player.currentTime;
    const other = edge === "start" ? (loop?.end ?? player.duration) : (loop?.start ?? 0);
    void setLoop(edge === "start" ? t : other, edge === "start" ? other : t);
  }

  function changeMix(next: StemMix) {
    player.setStemMix(next);
    mix = player.stemMix;
    custom = player.isStemMix;
  }

  function resetMix() {
    player.useFullRender();
    mix = player.stemMix;
    custom = false;
  }

  function isTyping(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) return false;
    if (target.closest("dialog[open]")) return true;
    if (target.isContentEditable || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return true;
    return target instanceof HTMLInputElement && !["range", "button", "checkbox", "radio"].includes(target.type);
  }

  function onKey(e: KeyboardEvent) {
    if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return;
    if (e.code === "Space") {
      e.preventDefault();
      toggle();
    } else if (e.key === "k" || e.key === "K") {
      e.preventDefault();
      void playPause();
    } else if (e.key === "[") {
      setLoopEdge("start");
    } else if (e.key === "]") {
      setLoopEdge("end");
    } else if (e.key === "Escape" && loop) {
      void clearLoop();
    }
  }

  let section: HTMLElement | undefined = $state();

  onMount(() => {
    player.onended = () => tick();
    // On a phone the result lands below the controls; bring it into view once.
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    section?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    window.addEventListener("keydown", onKey);
  });

  onDestroy(() => {
    cancelAnimationFrame(raf);
    window.removeEventListener("keydown", onKey);
    player.onended = null;
  });

  let mixDescription = $derived.by(() => {
    if (!custom) return "";
    const label = (n: string) => STEM_LABELS[n] ?? n;
    const parts: string[] = [];
    if (mix.solo.length) parts.push(`${mix.solo.map(label).join(" and ")} solo`);
    if (mix.muted.length) parts.push(`${mix.muted.map(label).join(" and ")} muted`);
    return parts.length ? `stem mix, ${parts.join(", ")}` : "stem mix, all stems";
  });

  let nowPlaying = $derived(side === "original" ? "Original stereo master" : "SoundStage spatial");
  let nowDetail = $derived(
    side === "original"
      ? "The excerpt exactly as uploaded, untouched."
      : [
          `${profileInfo(report.profile).label}, beta ${report.beta.toFixed(2)}`,
          report.mode === "stems" ? "rendered per stem" : "Lite, whole mix",
          report.fallback ? "stems unavailable, fell back to Lite" : "",
          mixDescription,
          "loudness matched to the original",
        ]
          .filter(Boolean)
          .join(" · "),
  );
</script>

<section bind:this={section} class="card player rise" aria-labelledby="player-title">
  <div class="now" aria-live="polite">
    <p class="eyebrow">{playing ? "Now playing" : "Paused on"}</p>
    <h2 id="player-title" class="now-title" class:spatial={side === "spatial"}>{nowPlaying}</h2>
    <p class="faint">{nowDetail}</p>
  </div>

  <div class="ab" role="group" aria-label="Choose what you hear">
    <button type="button" class="ab-btn" aria-pressed={side === "original"} onclick={() => choose("original")}>
      <span class="ab-name">Original</span>
      <span class="ab-sub">stereo master</span>
    </button>
    <button type="button" class="ab-btn" aria-pressed={side === "spatial"} onclick={() => choose("spatial")}>
      <span class="ab-name">Spatial</span>
      <span class="ab-sub">SoundStage</span>
    </button>
    <span class="thumb" class:right={side === "spatial"} aria-hidden="true"></span>
  </div>

  <div class="transport">
    <button type="button" class="play" onclick={playPause} aria-label={playing ? "Pause" : "Play"}>
      <Icon name={playing ? "pause" : "play"} size={26} />
    </button>
    <div class="track">
      <p class="track-name">{trackName}</p>
      <p class="time mono"><span>{formatPrecise(time)}</span> / {formatTime(player.duration)}</p>
    </div>
    <span class="hp faint"><Icon name="headphones" size={18} /> Headphones</span>
  </div>

  <Waveform
    channels={side === "original" ? channels.original : channels.spatial}
    duration={player.duration}
    {time}
    {loop}
    onseek={seek}
    onloop={setLoop}
  />

  <div class="loop-row">
    <span class="loop-state">
      <Icon name="loop" size={18} />
      {#if loop}
        Looping {formatPrecise(loop.start)} to {formatPrecise(loop.end)}
      {:else}
        Drag across the waveform to loop a passage
      {/if}
    </span>
    <span class="loop-actions">
      <button type="button" class="btn btn-sm btn-ghost" onclick={() => setLoopEdge("start")}>Loop from here</button>
      <button type="button" class="btn btn-sm btn-ghost" onclick={() => setLoopEdge("end")}>Loop to here</button>
      {#if loop}<button type="button" class="btn btn-sm" onclick={clearLoop}>Clear loop</button>{/if}
    </span>
  </div>

  {#if player.stemNames.length}
    <StemMixer names={player.stemNames} {mix} {custom} onchange={changeMix} onreset={resetMix} />
  {/if}

  <p class="keys faint">
    <kbd>Space</kbd> switch original and spatial · <kbd>K</kbd> play or pause · <kbd>[</kbd> <kbd>]</kbd> loop from and to
    here · <kbd>Esc</kbd> clear loop · arrow keys on the waveform seek
  </p>
</section>

<style>
  .player {
    scroll-margin-top: 72px;
    display: grid;
    gap: 20px;
  }
  .now {
    display: grid;
    gap: 4px;
    min-height: 92px;
  }
  .now-title {
    font-size: clamp(28px, 7vw, 40px);
    line-height: 1.1;
    font-weight: 800;
    letter-spacing: -0.025em;
    transition: color var(--dur) var(--ease);
  }
  .now-title.spatial {
    color: var(--accent);
  }
  .ab {
    position: relative;
    display: grid;
    grid-template-columns: 1fr 1fr;
    padding: 6px;
    border-radius: 24px;
    background: var(--bg);
    border: 1px solid var(--line);
    isolation: isolate;
  }
  .thumb {
    position: absolute;
    z-index: -1;
    top: 6px;
    bottom: 6px;
    left: 6px;
    width: calc(50% - 6px);
    border-radius: 18px;
    background: var(--surface-3);
    transition: transform 260ms var(--ease), background 260ms var(--ease);
  }
  .thumb.right {
    transform: translateX(100%);
    background: var(--accent);
  }
  .ab-btn {
    display: grid;
    justify-items: center;
    gap: 2px;
    min-height: 84px;
    border: 0;
    border-radius: 18px;
    background: transparent;
    color: var(--text-2);
    transition: color 260ms var(--ease);
  }
  .ab-btn[aria-pressed="true"] {
    color: var(--text);
  }
  .ab-btn:last-of-type[aria-pressed="true"] {
    color: var(--accent-ink);
  }
  .ab-name {
    align-self: end;
    font-size: 22px;
    font-weight: 800;
    letter-spacing: -0.01em;
  }
  .ab-sub {
    align-self: start;
    font-size: 13px;
    font-weight: 600;
    opacity: 0.8;
  }
  .transport {
    display: flex;
    align-items: center;
    gap: 14px;
  }
  .play {
    flex: none;
    display: grid;
    place-items: center;
    width: 60px;
    height: 60px;
    border-radius: 50%;
    border: 0;
    background: var(--text);
    color: var(--bg);
    transition: transform var(--dur) var(--ease);
  }
  .play:active {
    transform: scale(0.95);
  }
  .track {
    flex: 1;
    min-width: 0;
  }
  .track-name {
    font-weight: 700;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .time {
    color: var(--text-3);
  }
  .time span {
    color: var(--text);
  }
  .hp {
    display: none;
    align-items: center;
    gap: 6px;
  }
  .loop-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    font-size: 14px;
  }
  .loop-state {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: var(--text-2);
  }
  .loop-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  .keys {
    font-size: 12.5px;
    line-height: 1.8;
  }
  kbd {
    font-family: var(--mono);
    font-size: 11px;
    padding: 1px 6px;
    border-radius: 5px;
    border: 1px solid var(--line-strong);
    background: var(--surface-2);
    color: var(--text-2);
  }
  @media (min-width: 560px) {
    .hp {
      display: inline-flex;
    }
  }
  @media (hover: none) {
    .keys {
      display: none;
    }
  }
</style>
