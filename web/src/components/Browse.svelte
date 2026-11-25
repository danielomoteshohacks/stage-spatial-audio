<script lang="ts">
  // Browse and search. Genre cards open a genre page; the search box searches the catalogue (the
  // listed tracks first, then more from the sources); an artist's name opens their page.
  import { catalog, type Shelf, type Track } from "../lib/v3";
  import { fromTrack, type Item } from "../lib/items";
  import { hashTint, tintStyle } from "../lib/tint";
  import Art from "./Art.svelte";
  import Icon from "./Icon.svelte";

  let {
    backend,
    shelves,
    initial = "",
    onplay,
  }: { backend: string; shelves: Shelf[]; initial?: string; onplay: (i: Item, queue: Item[]) => void } = $props();

  let q = $state("");
  let view: { kind: "home" | "genre" | "search" | "artist"; title: string; tracks: Track[] } = $state({
    kind: "home",
    title: "",
    tracks: [],
  });
  let busy = $state(false);
  let error = $state("");
  let timer: ReturnType<typeof setTimeout> | undefined;
  let token = 0;

  async function run<T>(fn: () => Promise<T>): Promise<T | null> {
    const mine = ++token;
    busy = true;
    error = "";
    try {
      const r = await fn();
      return mine === token ? r : null;
    } catch (e) {
      if (mine === token) error = e instanceof Error ? e.message : "The search failed.";
      return null;
    } finally {
      if (mine === token) busy = false;
    }
  }

  async function openGenre(key: string) {
    const s = shelves.find((x) => x.key === key);
    view = { kind: "genre", title: s?.title ?? key, tracks: s?.tracks ?? [] };
    const more = await run(() => catalog.genre(backend, key));
    if (more) view = { kind: "genre", title: more.title, tracks: more.tracks };
    // The shelf's own songs are already listed; "more from the server" failing is not an error.
    else if (view.tracks.length) error = "";
  }

  async function openArtist(name: string) {
    view = { kind: "artist", title: name, tracks: [] };
    const r = await run(() => catalog.artist(backend, name));
    if (r) view = { kind: "artist", title: name, tracks: r.tracks };
  }

  function onInput() {
    clearTimeout(timer);
    if (!q.trim()) {
      view = { kind: "home", title: "", tracks: [] };
      return;
    }
    timer = setTimeout(async () => {
      const term = q.trim();
      // The server searches the sources live; when it is asleep, search the shelves already here,
      // so search never comes back empty-handed just because the server is waking.
      const r = await run(() => catalog.search(backend, term)).catch(() => null);
      const tracks = r?.tracks ?? localSearch(term);
      view = { kind: "search", title: `Results for "${term}"`, tracks };
      if (!r) error = "";
    }, 350);
  }

  function localSearch(term: string): Track[] {
    const t = term.toLowerCase();
    // eslint-disable-next-line svelte/prefer-svelte-reactivity -- local to one search, never rendered
    const seen = new Set<string>();
    const out: Track[] = [];
    for (const s of shelves)
      for (const tr of s.tracks)
        if (!seen.has(tr.id) && [tr.title, tr.artist, ...(tr.genres ?? []), s.title].some((x) => x?.toLowerCase().includes(t))) {
          seen.add(tr.id);
          out.push(tr);
        }
    return out;
  }

  $effect(() => {
    if (initial) void openGenre(initial);
  });

  const items = $derived(view.tracks.map(fromTrack));
  const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
</script>

<main class="screen" id="main">
  <h1>Browse</h1>
  <div class="search">
    <Icon name="search" size={18} />
    <input
      type="search"
      placeholder="Songs, artists, genres"
      aria-label="Search the catalogue"
      bind:value={q}
      oninput={onInput}
      maxlength="80"
    />
  </div>

  {#if view.kind === "home"}
    <div class="grid">
      {#each shelves as s (s.key)}
        <button type="button" class="genre" style={tintStyle(hashTint(s.key))} onclick={() => openGenre(s.key)}>
          <span>{s.title}</span>
        </button>
      {/each}
    </div>
    {#if !shelves.length}<p class="muted">The catalogue has not loaded yet.</p>{/if}
  {:else}
    <div class="bar">
      <button type="button" class="btn ghost" onclick={() => { view = { kind: "home", title: "", tracks: [] }; q = ""; }}>
        <Icon name="back" size={18} />Back
      </button>
      <h2>{view.title}</h2>
    </div>
    {#if error}<p role="alert" class="muted">{error}</p>{/if}
    {#if busy && !items.length}<p class="muted" role="status">Searching</p>{/if}
    <ul class="rows">
      {#each items as it (it.id)}
        <li>
          <button type="button" class="row" onclick={() => onplay(it, items)}>
            <Art id={it.artId ?? it.id} src={it.artworkUrl} size={52} radius={10} />
            <span class="meta">
              <span class="t">{it.title}</span>
              <span class="a">{it.artist} · {it.licence}</span>
            </span>
            <span class="d">{mmss(it.durationS)}</span>
          </button>
          {#if view.kind !== "artist"}
            <button type="button" class="artist" onclick={() => openArtist(it.artist)} aria-label="More from {it.artist}">
              <Icon name="list" size={18} />
            </button>
          {/if}
        </li>
      {/each}
    </ul>
    {#if !busy && !items.length && !error}<p class="muted">Nothing found. Try a genre or an artist's name.</p>{/if}
  {/if}
</main>

<style>
  h1 {
    font-size: var(--text-hero);
  }
  .search {
    display: flex;
    align-items: center;
    gap: var(--gap-3);
    margin-top: var(--gap-4);
    padding: 0 var(--gap-4);
    min-height: 48px;
    border-radius: var(--radius-pill);
    background: var(--surface);
    border: 1px solid var(--hairline-strong);
    box-shadow: var(--shadow-1);
    color: var(--text-2);
  }
  input {
    flex: 1;
    border: 0;
    background: transparent;
    min-height: 44px;
    outline: none;
    color: var(--text);
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: var(--gap-3);
    margin-top: var(--gap-5);
  }
  .genre {
    min-height: 92px;
    border: 0;
    border-radius: var(--radius-md);
    padding: var(--gap-4);
    text-align: left;
    font-family: var(--font-display);
    font-size: var(--text-lg);
    color: #fff;
    background:
      linear-gradient(180deg, rgb(255 255 255 / 0.2), transparent 50%),
      linear-gradient(145deg, var(--tint-1), var(--tint-2));
    box-shadow: var(--shadow-2);
    text-shadow: 0 1px 2px rgb(0 0 0 / 0.35);
    transition: transform var(--dur-2) var(--spring);
  }
  .genre:active {
    transform: scale(0.97);
  }
  .bar {
    display: flex;
    align-items: center;
    gap: var(--gap-3);
    margin-top: var(--gap-4);
  }
  .bar h2 {
    font-size: var(--text-xl);
  }
  .rows {
    list-style: none;
    margin: var(--gap-3) 0 0;
    padding: 0;
    display: grid;
  }
  .rows li {
    display: flex;
    align-items: center;
    border-bottom: 1px solid var(--hairline);
  }
  .row {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: var(--gap-3);
    border: 0;
    background: transparent;
    padding: var(--gap-2) 0;
    text-align: left;
    color: inherit;
  }
  .meta {
    display: grid;
    flex: 1;
    min-width: 0;
  }
  .t,
  .a {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .t {
    font-weight: 600;
  }
  .a,
  .d {
    font-size: var(--text-xs);
    color: var(--text-2);
  }
  .artist {
    width: 44px;
    height: 44px;
    border: 0;
    background: transparent;
    color: var(--text-2);
  }
</style>
