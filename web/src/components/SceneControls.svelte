<script lang="ts">
  // Space, Character, Motion depth and Genre. Changing any of them marks the render as stale;
  // "Apply" re-renders from the server's cache of this track (no upload, no new separation).
  import { CHARACTER_INFO, CHARACTERS, GENRES, motionLabel, SPACE_INFO, SPACES, type Character, type SpaceName } from "../lib/labels";

  let {
    space = $bindable(),
    character = $bindable(),
    motion = $bindable(),
    genre = $bindable(),
    detected = null,
    dirty = false,
    busy = false,
    canApply = true,
    onapply,
  }: {
    space: SpaceName;
    character: Character;
    motion: number;
    genre: string;
    detected?: string | null;
    dirty?: boolean;
    busy?: boolean;
    canApply?: boolean;
    onapply: () => void;
  } = $props();
</script>

<div class="controls">
  <div class="field">
    <label class="field-label" for="space">Space <span class="value">{SPACE_INFO[space].detail}</span></label>
    <select id="space" bind:value={space} disabled={busy}>
      {#each SPACES as s (s)}
        <option value={s}>{SPACE_INFO[s].label}</option>
      {/each}
    </select>
  </div>

  <div class="field">
    <div class="field-label" id="char-label">Character <span class="value">{CHARACTER_INFO[character].detail}</span></div>
    <div class="segmented" role="radiogroup" aria-labelledby="char-label">
      {#each CHARACTERS as c (c)}
        <button type="button" role="radio" aria-checked={character === c} disabled={busy} onclick={() => (character = c)}>
          {CHARACTER_INFO[c].label}
        </button>
      {/each}
    </div>
  </div>

  <div class="field">
    <label class="field-label" for="motion">Motion <span class="value">{motionLabel(motion)}</span></label>
    <input
      id="motion"
      type="range"
      min="0"
      max="1"
      step="0.05"
      bind:value={motion}
      disabled={busy}
      style:--fill={`${motion * 100}%`}
      aria-valuetext={motionLabel(motion)}
    />
    <p class="hint faint">Shakers and hats move with the groove. The vocal, bass and kick never move.</p>
  </div>

  <div class="field">
    <label class="field-label" for="genre">Genre <span class="value">{genre === "auto" && detected ? `Detected: ${detected}` : ""}</span></label>
    <select id="genre" bind:value={genre} disabled={busy}>
      {#each GENRES as g (g.id)}
        <option value={g.id}>{g.label}</option>
      {/each}
    </select>
  </div>

  {#if dirty}
    <button class="btn primary apply" type="button" disabled={busy || !canApply} onclick={onapply}>
      {busy ? "Rendering" : "Apply"}
    </button>
    {#if !canApply}
      <p class="hint faint">This render came from your library and its server copy has expired. Drop the track again to change it.</p>
    {/if}
  {/if}
</div>

<style>
  .controls {
    display: grid;
    gap: var(--gap-5);
  }

  .hint {
    font-size: var(--text-xs);
  }

  .apply {
    width: 100%;
  }
</style>
