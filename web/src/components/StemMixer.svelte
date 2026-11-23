<script lang="ts">
  import type { StemMix } from "../lib/engine";
  import { STEM_LABELS } from "../lib/labels";

  let {
    names,
    mix,
    custom,
    onchange,
    onreset,
  }: {
    names: string[];
    mix: StemMix;
    custom: boolean;
    onchange: (mix: StemMix) => void;
    onreset: () => void;
  } = $props();

  function flip(list: string[], name: string): string[] {
    return list.includes(name) ? list.filter((n) => n !== name) : [...list, name];
  }
</script>

<section class="mixer" aria-labelledby="mixer-title">
  <div class="head">
    <div>
      <p class="eyebrow">Spatial stems</p>
      <h3 id="mixer-title" class="title">{custom ? "Live stem mix" : "Full spatial render"}</h3>
    </div>
    <button type="button" class="btn btn-sm" onclick={onreset} disabled={!custom}>Use full spatial render</button>
  </div>
  <ul>
    {#each names as name (name)}
      {@const solo = mix.solo.includes(name)}
      {@const muted = mix.muted.includes(name)}
      {@const audible = (mix.solo.length === 0 || solo) && !muted}
      <li class:silent={custom && !audible}>
        <span class="name">{STEM_LABELS[name] ?? name}</span>
        <button
          type="button"
          class="tog"
          class:on={solo}
          aria-pressed={solo}
          aria-label={`Solo ${STEM_LABELS[name] ?? name}`}
          onclick={() => onchange({ solo: flip(mix.solo, name), muted: mix.muted })}>S</button
        >
        <button
          type="button"
          class="tog"
          class:on={muted}
          aria-pressed={muted}
          aria-label={`Mute ${STEM_LABELS[name] ?? name}`}
          onclick={() => onchange({ solo: mix.solo, muted: flip(mix.muted, name) })}>M</button
        >
      </li>
    {/each}
  </ul>
  <p class="faint">Each stem was spatialised on its own. Solo and mute mix them live, in sync with the original.</p>
</section>

<style>
  .mixer {
    display: grid;
    gap: 12px;
    padding-top: 18px;
    border-top: 1px solid var(--line);
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    justify-content: space-between;
    align-items: flex-end;
  }
  .title {
    font-size: 17px;
    font-weight: 700;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 8px;
  }
  li {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 8px 8px 14px;
    border-radius: var(--radius-sm);
    background: var(--bg);
    border: 1px solid var(--line);
    transition: opacity var(--dur) var(--ease);
  }
  li.silent {
    opacity: 0.45;
  }
  .name {
    flex: 1;
    font-weight: 650;
  }
  .tog {
    width: 40px;
    height: 40px;
    border-radius: 10px;
    border: 1px solid var(--line-strong);
    background: var(--surface-2);
    font-weight: 800;
    font-size: 14px;
    color: var(--text-2);
  }
  .tog.on {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--accent-ink);
  }
</style>
