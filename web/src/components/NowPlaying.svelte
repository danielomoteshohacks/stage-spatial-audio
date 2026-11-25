<script lang="ts">
  // The full-screen player: cover art on a gradient taken from the track's own colours, the format
  // pill, a scrubber that also shows how much of the spatial render exists, big soft controls, and
  // underneath the stage with every object live, the queue, and the details a listener may want
  // (licence and credit, the guard's verdict, downloads, the calibration game).
  import type { Item } from "../lib/items";
  import { hashTint, tintStyle } from "../lib/tint";
  import type { Plan3 } from "../lib/scene3";
  import type { Side } from "../lib/stream";
  import Art from "./Art.svelte";
  import GuardBadge from "./GuardBadge.svelte";
  import Icon from "./Icon.svelte";
  import PlayButton from "./PlayButton.svelte";
  import Scrubber from "./Scrubber.svelte";
  import SpatialPill from "./SpatialPill.svelte";

  let {
    item,
    queue,
    index,
    playing,
    busy,
    buffering,
    time,
    duration,
    readyUntil,
    renderProgress,
    spatialReady,
    side,
    plan,
    guard,
    feel,
    canFeel,
    downloads,
    onclose,
    ontoggle,
    onseek,
    onside,
    onprev,
    onnext,
    onpick,
    onfeel,
    oncalibrate,
  }: {
    item: Item;
    queue: Item[];
    index: number;
    playing: boolean;
    busy: boolean;
    buffering: boolean;
    time: number;
    duration: number;
    readyUntil: number;
    renderProgress: number;
    spatialReady: boolean;
    side: Side;
    plan: Plan3 | null;
    guard: { verdict: "pass" | "review" | "fail"; reasons: string[]; coverage?: { analysed_s: number; song_s: number; full: boolean } | null } | null;
    feel: boolean;
    canFeel: boolean;
    downloads: { label: string; url: string; file: string }[];
    onclose: () => void;
    ontoggle: () => void;
    onseek: (t: number) => void;
    onside: (s: Side) => void;
    onprev: () => void;
    onnext: () => void;
    onpick: (i: number) => void;
    onfeel: () => void;
    oncalibrate: () => void;
  } = $props();

  let panel: "stage" | "queue" | "about" = $state("stage");
  const style = $derived(tintStyle(hashTint(item.artId ?? item.id)));
  const lic = $derived(item.track?.licence);
</script>

<div class="np" style={style}>
  <header>
    <button type="button" class="btn icon ghost" onclick={onclose} aria-label="Close the player">
      <Icon name="chevron-down" size={24} />
    </button>
    <span class="eyebrow">Now playing</span>
    <button
      type="button"
      class="btn icon ghost"
      onclick={() => (panel = "queue")}
      aria-label="Show the queue"
    >
      <Icon name="queue" size={22} />
    </button>
  </header>

  <div class="hero">
    <div class="art"><Art id={item.artId ?? item.id} src={item.artworkUrl} size={280} radius={28} label="Cover art" /></div>
    <div class="title">
      <h1>{item.title}</h1>
      <p class="muted">{item.artist}</p>
    </div>
  </div>

  <SpatialPill {side} {spatialReady} progress={renderProgress} {buffering} onchange={onside} />

  <div class="transport">
    <Scrubber {time} {duration} ready={readyUntil} {onseek} />
    <div class="controls">
      <button type="button" class="btn icon ghost" onclick={onprev} aria-label="Previous" disabled={index <= 0}>
        <Icon name="prev" size={24} />
      </button>
      <PlayButton {playing} {busy} size={84} onclick={ontoggle} />
      <button type="button" class="btn icon ghost" onclick={onnext} aria-label="Next" disabled={index >= queue.length - 1}>
        <Icon name="next" size={24} />
      </button>
    </div>
  </div>

  <div class="tools">
    {#if canFeel}
      <button type="button" class="chip" aria-pressed={feel} onclick={onfeel}>Feel the bass</button>
    {/if}
    <button type="button" class="chip" onclick={oncalibrate}><Icon name="ear" size={16} />&nbsp;Fit to my ears</button>
    {#if guard}<GuardBadge verdict={guard.verdict} reasons={guard.reasons} coverage={guard.coverage} />{/if}
  </div>

  <div class="tabs" role="tablist" aria-label="More about this track">
    {#each [["stage", "Stage"], ["queue", "Queue"], ["about", "About"]] as [id, label] (id)}
      <button role="tab" type="button" aria-selected={panel === id} class="chip" onclick={() => (panel = id as typeof panel)}>
        {label}
      </button>
    {/each}
  </div>

  <div class="panel" role="tabpanel">
    {#if panel === "stage"}
      {#if plan}
        {#await import("./StageView.svelte") then m}
          <m.default {plan} {time} />
        {/await}
      {:else}
        <p class="muted">The stage appears when the first part of the song has been placed.</p>
      {/if}
    {:else if panel === "queue"}
      <ol class="queue">
        {#each queue as q, i (q.id)}
          <li>
            <button type="button" aria-current={i === index ? "true" : undefined} onclick={() => onpick(i)}>
              <Art id={q.id} src={q.artworkUrl} size={40} radius={8} />
              <span class="qm"><span class="qt">{q.title}</span><span class="qa">{q.artist}</span></span>
            </button>
          </li>
        {/each}
      </ol>
    {:else}
      <div class="about matte">
        {#if lic}
          <p>
            <strong>Licence:</strong>
            <a href={lic.url} target="_blank" rel="noopener noreferrer">{lic.label}</a>
            {#if lic.share_alike}(the spatial version is shared under the same licence){/if}
          </p>
          <p class="small muted">{item.track?.attribution}</p>
          <p>
            <a href={item.track?.landing_url} target="_blank" rel="noopener noreferrer">The track's own page</a>
          </p>
        {:else}
          <p>Your own file. It is processed on the server and deleted; a copy stays on this device only.</p>
        {/if}
        {#if plan}
          <p class="small muted">
            Genre: {plan.genre ?? "unknown"} · space: {plan.space === "dry_stage" ? "Dry stage" : plan.space} · head: {plan.hrtf ?? "D1"}
          </p>
        {/if}
        {#if downloads.length}
          <div class="dl">
            {#each downloads as d (d.url)}
              <a class="btn" href={d.url} download={d.file}><Icon name="download" size={16} />{d.label}</a>
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  </div>
</div>

<style>
  .np {
    min-height: 100dvh;
    display: grid;
    align-content: start;
    gap: var(--gap-4);
    padding: 0 var(--gap-5) var(--gap-7);
    background:
      radial-gradient(120% 55% at 50% 0%, color-mix(in srgb, var(--tint-1) 42%, var(--bg)), transparent 70%),
      linear-gradient(180deg, color-mix(in srgb, var(--tint-2) 20%, var(--bg)) 0%, var(--bg) 62%);
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .hero {
    display: grid;
    gap: var(--gap-5);
    justify-items: center;
  }
  .art :global(.art) {
    width: min(280px, 72vw);
    height: min(280px, 72vw);
    box-shadow: var(--shadow-3);
  }
  .title {
    text-align: center;
    max-width: 100%;
  }
  h1 {
    font-size: var(--text-xl);
    overflow-wrap: anywhere;
  }
  .transport {
    display: grid;
    gap: var(--gap-3);
    max-width: 520px;
    width: 100%;
    margin: 0 auto;
  }
  .controls {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--gap-6);
  }
  .tools {
    display: flex;
    flex-wrap: wrap;
    gap: var(--gap-2);
    justify-content: center;
  }
  .tabs {
    display: flex;
    gap: var(--gap-2);
    justify-content: center;
  }
  .panel {
    max-width: 560px;
    width: 100%;
    margin: 0 auto;
  }
  .queue {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 2px;
  }
  .queue button {
    width: 100%;
    display: flex;
    align-items: center;
    gap: var(--gap-3);
    border: 0;
    background: transparent;
    padding: var(--gap-2);
    border-radius: var(--radius-sm);
    text-align: left;
    color: inherit;
  }
  .queue button[aria-current="true"] {
    background: var(--accent-soft);
  }
  .qm {
    display: grid;
    min-width: 0;
  }
  .qt {
    font-weight: 600;
    font-size: var(--text-sm);
  }
  .qa {
    font-size: var(--text-xs);
    color: var(--text-2);
  }
  .about {
    padding: var(--gap-4);
    display: grid;
    gap: var(--gap-3);
  }
  .dl {
    display: flex;
    flex-wrap: wrap;
    gap: var(--gap-2);
  }
</style>
