<script lang="ts">
  import { formatTime } from "../lib/format";
  import { MODE_INFO, profileInfo, widthLabel } from "../lib/labels";
  import Icon from "./Icon.svelte";

  const LENGTHS = [15, 30, 60, 120];

  let {
    profiles,
    modes,
    duration,
    mode = $bindable(),
    profile = $bindable(),
    beta = $bindable(),
    start = $bindable(),
    seconds = $bindable(),
    disabled = false,
  }: {
    profiles: string[];
    modes: string[];
    duration: number | null;
    mode: "lite" | "stems";
    profile: string;
    beta: number;
    start: number | null;
    seconds: number;
    disabled?: boolean;
  } = $props();

  let length = $derived(duration ? Math.min(seconds, duration) : seconds);
  let maxStart = $derived(duration ? Math.max(0, duration - length) : 0);
  let fill = $derived(((beta - 1) / 1.4) * 100);

  let auto = $derived(start === null);
  let at = $derived(start ?? 0);

  $effect(() => {
    if (start !== null && start > maxStart) start = maxStart;
  });
</script>

<fieldset class="group" {disabled}>
  <legend class="eyebrow">Excerpt</legend>
  <div class="segmented" role="radiogroup" aria-label="Where to start">
    <button type="button" role="radio" aria-checked={auto} onclick={() => (start = null)}>Loudest part</button>
    <button type="button" role="radio" aria-checked={!auto} onclick={() => (start = at)}>Choose</button>
  </div>
  {#if auto}
    <p class="faint">The backend finds the loudest stretch, usually the chorus or the drop.</p>
  {:else if duration}
    <div class="excerpt">
      <label class="field-label" for="start">
        Start at <span class="value">{formatTime(at)}</span>
        <span class="faint">to {formatTime(at + length)} of {formatTime(duration)}</span>
      </label>
      <input
        id="start"
        type="range"
        min="0"
        max={maxStart}
        step="1"
        bind:value={start}
        style:--fill={`${maxStart ? (at / maxStart) * 100 : 0}%`}
        aria-valuetext={`${formatTime(at)} to ${formatTime(at + length)}`}
      />
    </div>
  {:else}
    <label class="field-label" for="start-num">Start (seconds)</label>
    <input id="start-num" class="input" type="number" min="0" step="1" bind:value={start} />
  {/if}
  <div class="field-label" id="len-label">Length</div>
  <div class="segmented" role="radiogroup" aria-labelledby="len-label">
    {#each LENGTHS as s (s)}
      <button type="button" role="radio" aria-checked={seconds === s} onclick={() => (seconds = s)}>
        {s < 60 ? `${s} s` : `${s / 60} min`}
      </button>
    {/each}
  </div>
</fieldset>

<fieldset class="group" {disabled}>
  <legend class="eyebrow">Mode</legend>
  <div class="segmented" role="radiogroup" aria-label="Mode">
    {#each modes as m (m)}
      <button type="button" role="radio" aria-checked={mode === m} onclick={() => (mode = m as "lite" | "stems")}>
        {MODE_INFO[m]?.label ?? m}
      </button>
    {/each}
  </div>
  <p class="faint">{MODE_INFO[mode]?.detail}</p>
</fieldset>

<fieldset class="group" {disabled}>
  <legend class="eyebrow">Character</legend>
  <div class="chips" role="radiogroup" aria-label="Spatial character">
    {#each profiles as p (p)}
      <button type="button" class="chip" role="radio" aria-checked={profile === p} onclick={() => (profile = p)}>
        <span class="chip-title">{profileInfo(p).label}</span>
        <span class="chip-detail">{profileInfo(p).detail}</span>
      </button>
    {/each}
  </div>
</fieldset>

<fieldset class="group" {disabled}>
  <legend class="eyebrow">Width</legend>
  <label class="field-label" for="beta">
    <span class="value">{widthLabel(beta)}</span>
  </label>
  <input
    id="beta"
    type="range"
    min="1"
    max="2.4"
    step="0.05"
    bind:value={beta}
    style:--fill={`${fill}%`}
    aria-valuetext={`${widthLabel(beta)}, beta ${beta.toFixed(2)}`}
  />
  <div class="scale faint" aria-hidden="true"><span>Original</span><span>Widest</span></div>
</fieldset>

<details class="advanced">
  <summary><span>Advanced</span><Icon name="chevron" size={18} /></summary>
  <div class="adv-body">
    <p class="faint">The technical names the engine and the run report use.</p>
    <dl>
      <dt>mode</dt><dd><code>{mode}</code></dd>
      <dt>profile</dt>
      <dd>
        <label class="sr-only" for="profile-id">Profile id</label>
        <select id="profile-id" class="input mono" bind:value={profile} {disabled}>
          {#each profiles as p (p)}<option value={p}>{p}</option>{/each}
        </select>
      </dd>
      <dt>beta</dt>
      <dd>
        <label class="sr-only" for="beta-num">Beta</label>
        <input id="beta-num" class="input mono" type="number" min="1" max="2.4" step="0.05" bind:value={beta} {disabled} />
      </dd>
      <dt>excerpt</dt><dd><code>start={start ?? "auto"} seconds={seconds}</code></dd>
    </dl>
    <p class="faint">
      Profiles V0 to V5 are the ablation chain of decision 0007: each adds one cue to the one before. <code>max</code> combines
      the cues whose objective gates passed. None of them is yet backed by a listening test.
    </p>
  </div>
</details>

<style>
  .group {
    border: 0;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 10px;
    min-width: 0;
  }
  .group + .group,
  .advanced {
    margin-top: 22px;
  }
  legend {
    padding: 0;
    margin-bottom: 10px;
  }
  .value {
    color: var(--accent);
  }
  .excerpt {
    display: grid;
    gap: 4px;
  }
  .chips {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 8px;
  }
  .chip {
    display: grid;
    gap: 2px;
    text-align: left;
    padding: 12px 14px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--line);
    background: var(--bg);
    transition: border-color var(--dur) var(--ease), background var(--dur) var(--ease);
  }
  .chip:hover {
    border-color: var(--line-strong);
  }
  .chip[aria-checked="true"] {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .chip-title {
    font-weight: 700;
    font-size: 15px;
  }
  .chip-detail {
    font-size: 12.5px;
    line-height: 1.35;
    color: var(--text-2);
  }
  .scale {
    display: flex;
    justify-content: space-between;
    font-size: 12px;
  }
  .advanced {
    border-top: 1px solid var(--line);
    padding-top: 6px;
  }
  summary {
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 44px;
    cursor: pointer;
    font-weight: 650;
    color: var(--text-2);
    list-style: none;
  }
  summary::-webkit-details-marker {
    display: none;
  }
  summary :global(svg) {
    transition: transform var(--dur) var(--ease);
  }
  details[open] summary :global(svg) {
    transform: rotate(180deg);
  }
  .adv-body {
    display: grid;
    gap: 12px;
    padding-bottom: 6px;
  }
  dl {
    display: grid;
    grid-template-columns: 80px 1fr;
    gap: 8px 12px;
    align-items: center;
    margin: 0;
  }
  dt {
    font-family: var(--mono);
    font-size: 13px;
    color: var(--text-3);
  }
  dd {
    margin: 0;
    min-width: 0;
  }
</style>
