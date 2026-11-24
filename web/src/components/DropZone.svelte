<script lang="ts">
  // Drop a file or tap to choose one. Only the file's name and tags are read here; the audio is
  // sent to the server when the render starts.
  import { ALLOWED } from "../lib/format";
  import Icon from "./Icon.svelte";

  let { disabled = false, onfile }: { disabled?: boolean; onfile: (f: File) => void } = $props();
  let over = $state(false);
  let input: HTMLInputElement | undefined = $state();
  let refused = $state("");

  function take(f: File | undefined | null) {
    if (!f) return;
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!ALLOWED.includes(ext)) {
      refused = `${f.name} is not a file SoundStage can read. Choose wav, flac, mp3, ogg or m4a.`;
      return;
    }
    refused = "";
    onfile(f);
  }
</script>

<button
  type="button"
  class="drop glass"
  class:over
  {disabled}
  onclick={() => input?.click()}
  ondragover={(e) => {
    e.preventDefault();
    over = true;
  }}
  ondragleave={() => (over = false)}
  ondrop={(e) => {
    e.preventDefault();
    over = false;
    take(e.dataTransfer?.files?.[0]);
  }}
>
  <span class="ring" aria-hidden="true"><Icon name="upload" size={26} /></span>
  <span class="title">Drop a song</span>
  <span class="faint">or tap to choose one: wav, flac, mp3, ogg or m4a, up to 12 minutes</span>
</button>
<input bind:this={input} class="sr-only" type="file" accept=".wav,.flac,.mp3,.ogg,.m4a,audio/*" tabindex="-1" aria-hidden="true"
  onchange={(e) => take((e.currentTarget as HTMLInputElement).files?.[0])} />
{#if refused}<p class="refused" role="alert">{refused}</p>{/if}

<style>
  .drop {
    width: 100%;
    display: grid;
    justify-items: center;
    gap: var(--gap-2);
    padding: var(--gap-6) var(--gap-5);
    cursor: pointer;
    text-align: center;
    border-style: dashed;
    transition: border-color var(--dur-2) var(--ease), transform var(--dur-2) var(--ease);
  }

  .drop.over {
    border-color: var(--lagoon);
    transform: scale(1.01);
  }

  .ring {
    width: 56px;
    height: 56px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: rgb(31 200 180 / 0.12);
    color: var(--lagoon);
    box-shadow: 0 0 0 10px rgb(31 200 180 / 0.05);
  }

  .title {
    font-family: var(--font-display);
    font-size: var(--text-xl);
  }

  .faint {
    font-size: var(--text-sm);
  }

  .refused {
    margin-top: var(--gap-2);
    color: var(--coral);
    font-size: var(--text-sm);
  }
</style>
