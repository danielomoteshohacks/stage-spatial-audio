<script lang="ts">
  // Home, laid out like a streaming app's front page: a featured track with its cover filling a
  // glossy card, quick genre tiles, then every shelf. The shelves come from the committed catalogue
  // at once and from the server when it answers, so this page is never empty.
  import { greeting, type Item } from "../lib/items";
  import type { Shelf as ShelfT } from "../lib/v3";
  import { fromTrack } from "../lib/items";
  import { hashTint, tintStyle } from "../lib/tint";
  import Shelf from "./Shelf.svelte";
  import Art from "./Art.svelte";
  import Icon from "./Icon.svelte";

  let {
    recents,
    shelves,
    status,
    onplay,
    onbrowse,
    oncreate,
  }: {
    recents: Item[];
    shelves: ShelfT[];
    status: "checking" | "online" | "offline";
    onplay: (i: Item, queue: Item[]) => void;
    onbrowse: (genre?: string) => void;
    oncreate: () => void;
  } = $props();

  const hello = greeting(new Date().getHours());
  const items = (s: ShelfT) => s.tracks.map(fromTrack);
  const spatial = $derived(shelves.find((s) => s.key === "made_for_spatial"));
  const others = $derived(shelves.filter((s) => s.key !== "made_for_spatial"));
  // The featured track changes with the day, so the front page is not the same every visit.
  const featured = $derived.by(() => {
    const pool = spatial ? items(spatial) : shelves.length ? items(shelves[0]) : [];
    return pool.length ? pool[new Date().getDate() % pool.length] : null;
  });
  const featuredQueue = $derived(spatial ? items(spatial) : shelves.length ? items(shelves[0]) : []);
  const tiles = $derived(others.slice(0, 6));
  const total = $derived(shelves.reduce((n, s) => n + s.tracks.length, 0));
</script>

<main class="screen home" id="main">
  {#if featured}
    <div class="wash" style={tintStyle(hashTint(featured.id))} aria-hidden="true"></div>
  {/if}

  <header class="top">
    <h1 class="hero">{hello}</h1>
    <span class="status" data-s={status} role="status">
      <span class="dot"></span>{status === "online" ? "Spatial ready" : status === "checking" ? "Waking the server" : "Originals only"}
    </span>
  </header>

  {#if featured}
    <section class="feature gloss" style={tintStyle(hashTint(featured.id))} aria-label="Featured">
      {#if featured.artworkUrl}<img class="bgart" src={featured.artworkUrl} alt="" aria-hidden="true" onerror={(e) => ((e.currentTarget as HTMLImageElement).style.display = "none")} />{/if}
      <div class="feature-in">
        <Art id={featured.id} src={featured.artworkUrl} size={132} radius={18} eager label={`Cover of ${featured.title}`} />
        <div class="meta">
          <span class="kicker">Made for spatial</span>
          <h2 class="ft">{featured.title}</h2>
          <span class="fa">{featured.artist}</span>
          <div class="actions">
            <button type="button" class="play" aria-label={`Play ${featured.title}`} onclick={() => onplay(featured, featuredQueue)}>
              <Icon name="play" size={26} />
            </button>
            <span class="pill">Spatial</span>
          </div>
        </div>
      </div>
    </section>
  {/if}

  {#if tiles.length}
    <section class="tiles" aria-label="Genres">
      {#each tiles as s (s.key)}
        <button type="button" class="tile" style={tintStyle(hashTint(s.key))} onclick={() => onbrowse(s.key)}>
          <span class="tile-t">{s.title}</span>
          {#if s.tracks[0]?.artwork_url}<img src={s.tracks[0].artwork_url} alt="" loading="lazy" onerror={(e) => ((e.currentTarget as HTMLImageElement).style.display = "none")} />{/if}
        </button>
      {/each}
    </section>
  {/if}

  {#if recents.length}
    <Shelf title="Jump back in" items={recents} onplay={(i) => onplay(i, recents)} />
  {/if}
  {#if spatial}
    <Shelf first title="Made for spatial" items={items(spatial)} onplay={(i) => onplay(i, items(spatial))} onmore={() => onbrowse("made_for_spatial")} />
  {/if}
  {#each others as s (s.key)}
    <Shelf title={s.title} items={items(s)} onplay={(i) => onplay(i, items(s))} onmore={() => onbrowse(s.key)} />
  {/each}

  {#if !shelves.length}
    <div class="skeleton" aria-hidden="true">
      {#each [0, 1] as k (k)}
        <div class="sk-shelf"><span class="sk-title"></span><div class="sk-row">{#each [0, 1, 2] as j (j)}<span class="sk-card"></span>{/each}</div></div>
      {/each}
    </div>
  {/if}

  <section class="make gloss">
    <div>
      <h2>Your own song</h2>
      <p class="muted">Upload a track you own. You hear it spatial from the first seconds while the rest is made.</p>
    </div>
    <button type="button" class="btn primary" onclick={oncreate}>Create</button>
  </section>

  {#if total}
    <p class="foot muted">{total} openly licensed songs from independent artists. Every one is credited in Credits.</p>
  {/if}
</main>

<style>
  .home {
    position: relative;
    isolation: isolate;
  }
  /* The colour of the featured cover washes down from the top, as streaming apps do. */
  .wash {
    position: absolute;
    inset: calc(-1 * var(--gap-6)) calc(-1 * var(--gap-5)) auto;
    height: 420px;
    z-index: -1;
    background:
      radial-gradient(120% 90% at 20% 0%, color-mix(in oklab, var(--tint-1) 55%, transparent), transparent 70%),
      radial-gradient(90% 80% at 90% 10%, color-mix(in oklab, var(--tint-2) 45%, transparent), transparent 70%);
    opacity: 0.55;
    pointer-events: none;
  }
  .top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--gap-3);
    margin-top: var(--gap-3);
  }
  .hero {
    font-size: var(--text-hero);
  }
  .status {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 12px;
    border-radius: var(--radius-pill);
    background: var(--overlay);
    backdrop-filter: blur(var(--blur));
    -webkit-backdrop-filter: blur(var(--blur));
    box-shadow: var(--shadow-1), inset 0 1px 0 var(--highlight);
    font-size: var(--text-xs);
    font-weight: 600;
    color: var(--text-2);
    white-space: nowrap;
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--review);
  }
  .status[data-s="online"] .dot {
    background: var(--pass);
    box-shadow: 0 0 0 4px var(--lagoon-soft);
  }
  .status[data-s="checking"] .dot {
    animation: pulse 1.2s ease-in-out infinite;
  }
  @keyframes pulse {
    50% {
      opacity: 0.3;
    }
  }

  /* A glossy card: a matte base, the cover blurred underneath, a light top edge. */
  .gloss {
    position: relative;
    overflow: hidden;
    border-radius: var(--radius-lg);
    background: var(--overlay);
    backdrop-filter: blur(var(--blur)) saturate(1.4);
    -webkit-backdrop-filter: blur(var(--blur)) saturate(1.4);
    box-shadow: var(--shadow-2), inset 0 1px 0 var(--highlight), inset 0 0 0 1px var(--hairline);
  }
  .feature {
    margin-top: var(--gap-5);
    padding: var(--gap-5);
    background:
      linear-gradient(180deg, rgb(255 255 255 / 0.14), transparent 40%),
      linear-gradient(135deg, color-mix(in oklab, var(--tint-1) 70%, #000 10%), color-mix(in oklab, var(--tint-2) 75%, #000 25%));
    color: #fff;
  }
  .bgart {
    position: absolute;
    inset: -20%;
    width: 140%;
    height: 140%;
    object-fit: cover;
    filter: blur(40px) saturate(1.3);
    opacity: 0.55;
    z-index: 0;
  }
  .feature-in {
    position: relative;
    z-index: 1;
    display: flex;
    gap: var(--gap-4);
    align-items: center;
  }
  .feature :global(.art) {
    box-shadow: 0 10px 30px rgb(0 0 0 / 0.35);
  }
  .meta {
    display: grid;
    gap: 2px;
    min-width: 0;
  }
  .kicker {
    font-size: var(--text-xs);
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    opacity: 0.85;
  }
  .ft {
    font-size: var(--text-xl);
    line-height: 1.1;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
  }
  .fa {
    opacity: 0.85;
    font-size: var(--text-sm);
  }
  .actions {
    display: flex;
    align-items: center;
    gap: var(--gap-3);
    margin-top: var(--gap-3);
  }
  .play {
    display: grid;
    place-items: center;
    width: 56px;
    height: 56px;
    border: 0;
    border-radius: 50%;
    color: #fff;
    background: radial-gradient(circle at 35% 30%, color-mix(in oklab, var(--lagoon) 70%, #fff 30%), var(--lagoon) 60%);
    box-shadow: var(--shadow-play), inset 0 1px 0 rgb(255 255 255 / 0.45);
    transition: transform var(--dur-2) var(--spring-bounce);
  }
  .play:active {
    transform: scale(0.92);
  }
  .pill {
    padding: 5px 12px;
    border-radius: var(--radius-pill);
    background: rgb(255 255 255 / 0.18);
    border: 1px solid rgb(255 255 255 / 0.35);
    backdrop-filter: blur(10px);
    font-size: var(--text-xs);
    font-weight: 700;
    letter-spacing: 0.04em;
  }

  .tiles {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: var(--gap-3);
    margin-top: var(--gap-5);
  }
  .tile {
    position: relative;
    overflow: hidden;
    height: 76px;
    border: 0;
    border-radius: var(--radius-md);
    padding: var(--gap-3);
    text-align: left;
    color: #fff;
    background:
      linear-gradient(180deg, rgb(255 255 255 / 0.16), transparent 50%),
      linear-gradient(135deg, var(--tint-1), var(--tint-2));
    box-shadow: var(--shadow-1), inset 0 1px 0 rgb(255 255 255 / 0.3);
    transition: transform var(--dur-2) var(--spring);
  }
  .tile:active {
    transform: scale(0.97);
  }
  .tile-t {
    position: relative;
    z-index: 1;
    font-weight: 700;
    font-size: var(--text-sm);
    line-height: 1.2;
    display: block;
    max-width: 70%;
    text-shadow: 0 1px 2px rgb(0 0 0 / 0.25);
  }
  /* The genre's first cover, tilted into the corner, as on a streaming app's browse page. */
  .tile img {
    position: absolute;
    right: -10px;
    bottom: -8px;
    width: 58px;
    height: 58px;
    border-radius: 8px;
    transform: rotate(22deg);
    box-shadow: 0 6px 14px rgb(0 0 0 / 0.3);
    object-fit: cover;
  }

  .make {
    margin-top: var(--gap-6);
    padding: var(--gap-5);
    display: flex;
    gap: var(--gap-4);
    align-items: center;
    justify-content: space-between;
  }
  .make h2 {
    font-size: var(--text-lg);
  }
  .make p {
    font-size: var(--text-sm);
    margin-top: 4px;
  }
  .foot {
    margin-top: var(--gap-5);
    font-size: var(--text-xs);
    text-align: center;
  }
  .skeleton {
    display: grid;
    gap: var(--gap-5);
    margin-top: var(--gap-5);
  }
  .sk-title {
    display: block;
    width: 55%;
    height: 32px;
    border-radius: 8px;
    background: var(--surface-3);
  }
  .sk-row {
    display: flex;
    gap: var(--gap-3);
    margin-top: var(--gap-3);
    height: 215px;
    overflow: hidden;
  }
  .sk-card {
    flex: none;
    width: 148px;
    height: 148px;
    border-radius: 16px;
    background: var(--surface-3);
  }
</style>
