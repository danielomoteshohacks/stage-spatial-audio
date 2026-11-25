<script lang="ts">
  // Credits and licences, what is streamed and from where, and the settings that are not part of
  // a song (the theme, the server). Everything here is also in the repository's models/MANIFEST.md
  // and decision records.
  import { catalog } from "../lib/v3";
  import type { ThemeChoice } from "../lib/theme";
  import { onMount } from "svelte";

  let {
    backend,
    theme,
    onbackend,
    ontheme,
    ontest,
  }: {
    backend: string;
    theme: ThemeChoice;
    onbackend: (url: string) => void;
    ontheme: (t: ThemeChoice) => void;
    ontest: () => void;
  } = $props();

  let legal: { what?: string; licences?: Record<string, number>; obligations?: Record<string, string>;
    streaming?: string; tracks_listed?: number; sources?: { name: string; url: string; note: string }[] } | null = $state(null);
  let draft = $derived(backend);

  onMount(() => {
    catalog.legal(backend).then((l) => (legal = l as typeof legal)).catch(() => (legal = null));
  });

  const MODELS: [string, string, string][] = [
    ["Kim Mel-Band RoFormer (vocals)", "MIT", "KimberleyJSN"],
    ["BS-RoFormer vocals, karaoke and dereverb models", "GPL-3.0, run on the server, not redistributed", "anvuew; training data by becruily"],
    ["DrumSep (kick, snare, toms, hi-hat, cymbals)", "CC BY-NC-SA 4.0, non-commercial research use only", "jarredou and aufr33"],
    ["htdemucs (four and six stems)", "MIT", "Meta AI Research"],
    ["Music-Source-Separation-Training", "MIT", "ZFTurbo"],
    ["BS-RoFormer and Mel-Band RoFormer papers", "", "Lu, Wang, Kong and Hung; Wang, Lu and Won"],
    ["Azimuth discrimination (ADRess)", "", "Barry, Lawlor and Coyle, DAFx 2004"],
    ["SADIE II head-related transfer functions", "Apache-2.0", "The Audio Lab, University of York (Armstrong, Thresh, Murphy and Kearney 2018)"],
    ["Instrument Sans and Instrument Serif", "SIL Open Font Licence 1.1", "Instrument"],
  ];
</script>

<main class="screen" id="main">
  <h1>Credits</h1>

  <section class="matte block">
    <h2>What is streamed</h2>
    {#if legal}
      <p>{legal.what}</p>
      <p class="muted">{legal.streaming}</p>
      {#if legal.licences}
        <ul class="plain">
          {#each Object.entries(legal.licences) as [k, v] (k)}<li>{v} tracks under {k}</li>{/each}
        </ul>
      {/if}
      {#if legal.obligations}
        <dl>
          {#each Object.entries(legal.obligations) as [k, v] (k)}<dt>{k}</dt><dd>{v}</dd>{/each}
        </dl>
      {/if}
      {#if legal.sources}
        <p class="small muted">
          From:
          {#each legal.sources as s, i (s.name)}{i ? ", " : ""}<a href={s.url} target="_blank" rel="noopener noreferrer">{s.name}</a>{/each}.
          Only openly licensed music is offered; a track that should not be here is removed on request.
        </p>
      {/if}
    {:else}
      <p class="muted">
        Only music under an open licence that permits adaptation is offered: CC BY, CC BY-SA, CC0 and public
        domain. Tracks under any NoDerivatives licence are never listed, because spatialising a song is an
        adaptation. Each track's page shows its creator, its licence and a link to the source. The server was not
        reachable, so the live list is not shown.
      </p>
    {/if}
  </section>

  <section class="matte block">
    <h2>Models, methods and data</h2>
    <ul class="plain">
      {#each MODELS as [n, l, by] (n)}<li><strong>{n}</strong>{l ? ` — ${l}` : ""}. {by}.</li>{/each}
    </ul>
    <p class="small muted">
      A model whose licence is not stated at its source is not used. Full table with checksums:
      <a href="https://github.com/danielomoteshohacks/stage-spatial-audio/blob/main/models/MANIFEST.md" target="_blank" rel="noopener noreferrer">models/MANIFEST.md</a>.
      SoundStage is an independent research project, not affiliated with or endorsed by Spotify, Apple or Dolby.
    </p>
  </section>

  <section class="matte block">
    <h2>Your files and your data</h2>
    <p>
      A song you upload is processed on the server and deleted within the hour. Renders you keep are stored on
      this device only. Nothing is tracked and nothing is sold.
    </p>
  </section>

  <section class="matte block">
    <h2>Settings</h2>
    <fieldset>
      <legend>Theme</legend>
      <div class="chips">
        {#each [["system", "Follow the system"], ["light", "Light"], ["dark", "Dark"]] as [id, label] (id)}
          <button type="button" class="chip" aria-pressed={theme === id} onclick={() => ontheme(id as ThemeChoice)}>{label}</button>
        {/each}
      </div>
    </fieldset>
    <label>Server
      <input type="url" bind:value={draft} />
    </label>
    <div class="chips">
      <button type="button" class="btn" onclick={() => onbackend(draft)}>Use this server</button>
      <button type="button" class="btn" onclick={ontest}>Listening test</button>
    </div>
  </section>
</main>

<style>
  h1 {
    font-size: var(--text-hero);
  }
  .block {
    margin-top: var(--gap-5);
    padding: var(--gap-5);
    display: grid;
    gap: var(--gap-3);
  }
  h2 {
    font-size: var(--text-xl);
  }
  .plain {
    margin: 0;
    padding-left: 1.1em;
    display: grid;
    gap: var(--gap-2);
  }
  dl {
    margin: 0;
    display: grid;
    gap: 2px;
    font-size: var(--text-sm);
  }
  dt {
    font-weight: 600;
  }
  dd {
    margin: 0 0 var(--gap-2);
    color: var(--text-2);
  }
  fieldset {
    border: 0;
    margin: 0;
    padding: 0;
  }
  legend {
    font-weight: 600;
    margin-bottom: var(--gap-2);
  }
  .chips {
    display: flex;
    gap: var(--gap-2);
    flex-wrap: wrap;
  }
  label {
    display: grid;
    gap: var(--gap-2);
    font-weight: 600;
  }
  input[type="url"] {
    min-height: 44px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--hairline-strong);
    background: var(--surface);
    padding: 0 var(--gap-3);
  }
</style>
