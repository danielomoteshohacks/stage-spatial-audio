<script lang="ts">
  import { formatBytes, formatTime } from "../lib/format";
  import Icon from "./Icon.svelte";

  const ACCEPT = ".wav,.flac,.mp3,.ogg,.m4a,audio/wav,audio/flac,audio/mpeg,audio/ogg,audio/mp4,audio/x-m4a";
  const ALLOWED = [".wav", ".flac", ".mp3", ".ogg", ".m4a"];

  let {
    file,
    duration,
    disabled = false,
    onfile,
  }: {
    file: File | null;
    duration: number | null;
    disabled?: boolean;
    onfile: (file: File) => void;
  } = $props();

  let input: HTMLInputElement | undefined = $state();
  let over = $state(false);
  let error = $state("");

  function accept(f: File | undefined | null) {
    if (!f) return;
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!ALLOWED.includes(ext)) {
      error = `${f.name} is not a supported type. Use wav, flac, mp3, ogg or m4a.`;
      return;
    }
    error = "";
    onfile(f);
  }

  function drop(e: DragEvent) {
    e.preventDefault();
    over = false;
    if (!disabled) accept(e.dataTransfer?.files?.[0]);
  }
</script>

<div
  class="zone"
  class:over
  class:has-file={!!file}
  role="presentation"
  ondragover={(e) => {
    e.preventDefault();
    if (!disabled) over = true;
  }}
  ondragleave={() => (over = false)}
  ondrop={drop}
>
  <input
    bind:this={input}
    id="track-input"
    class="sr-only"
    type="file"
    accept={ACCEPT}
    {disabled}
    onchange={(e) => accept((e.currentTarget as HTMLInputElement).files?.[0])}
  />
  {#if file}
    <div class="file">
      <span class="art" aria-hidden="true"><Icon name="music" size={22} /></span>
      <div class="meta">
        <p class="name">{file.name}</p>
        <p class="faint">{formatBytes(file.size)}{duration ? ` · ${formatTime(duration)}` : ""}</p>
      </div>
      <button type="button" class="btn btn-sm" {disabled} onclick={() => input?.click()}>Change</button>
    </div>
  {:else}
    <button type="button" class="pick" {disabled} onclick={() => input?.click()} aria-describedby="drop-help">
      <span class="badge" aria-hidden="true"><Icon name="upload" size={26} /></span>
      <span class="big">Drop a track or choose a file</span>
      <span id="drop-help" class="faint">wav, flac, mp3, ogg or m4a, up to 12 minutes</span>
    </button>
  {/if}
</div>
{#if error}<p class="err" role="alert">{error}</p>{/if}

<style>
  .zone {
    border: 1.5px dashed var(--line-strong);
    border-radius: var(--radius);
    background: var(--bg);
    transition: border-color var(--dur) var(--ease), background var(--dur) var(--ease);
  }
  .zone.over {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .zone.has-file {
    border-style: solid;
    border-color: var(--line);
  }
  .pick {
    width: 100%;
    display: grid;
    justify-items: center;
    gap: 8px;
    padding: 36px 16px;
    border: 0;
    background: transparent;
    border-radius: var(--radius);
    text-align: center;
  }
  .badge {
    display: grid;
    place-items: center;
    width: 56px;
    height: 56px;
    border-radius: 50%;
    background: var(--accent-soft);
    color: var(--accent);
    margin-bottom: 4px;
  }
  .big {
    font-size: 17px;
    font-weight: 700;
  }
  .file {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 14px;
  }
  .art {
    flex: none;
    display: grid;
    place-items: center;
    width: 48px;
    height: 48px;
    border-radius: 10px;
    background: linear-gradient(135deg, #3a2a0b, #1d1d24);
    color: var(--accent);
  }
  .meta {
    flex: 1;
    min-width: 0;
  }
  .name {
    font-weight: 700;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .err {
    margin-top: 8px;
    color: var(--danger);
    font-size: 14px;
  }
</style>
