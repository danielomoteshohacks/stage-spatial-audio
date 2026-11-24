<script lang="ts">
  // The now-playing sheet. It owns nothing but the view: the player, the reports and the plan
  // come from App, and every change goes back through callbacks.
  import type { GuardReport } from "../lib/api";
  import { clampLoop, type LoopRegion, type Side, type SyncPlayer } from "../lib/engine";
  import { formatTime } from "../lib/format";
  import { canVibrate } from "../lib/haptics";
  import { STEM_LABELS, type Character, type SpaceName } from "../lib/labels";
  import type { Plan } from "../lib/scene";
  import ABSwitch from "./ABSwitch.svelte";
  import GuardBadge from "./GuardBadge.svelte";
  import Icon from "./Icon.svelte";
  import Logo from "./Logo.svelte";
  import SceneControls from "./SceneControls.svelte";
  import Waveform from "./Waveform.svelte";

  let {
    player,
    channels,
    title,
    artist,
    artworkUrl,
    report,
    plan,
    detectedGenre,
    downloads,
    levels,
    time,
    playing,
    side,
    space = $bindable(),
    character = $bindable(),
    motion = $bindable(),
    genre = $bindable(),
    feel = $bindable(),
    feelIntensity = $bindable(),
    dirty,
    busy,
    canRerender,
    onapply,
    onplan,
    onrerenderplan,
    onclose,
    onplay,
    onside,
    onblindtest,
  }: {
    player: SyncPlayer;
    channels: Float32Array[];
    title: string;
    artist?: string;
    artworkUrl: string | null;
    report: GuardReport | null;
    plan: Plan | null;
    detectedGenre: string | null;
    downloads: { label: string; url: string; file: string }[];
    levels: Record<string, Float32Array>;
    time: number;
    playing: boolean;
    side: Side;
    space: SpaceName;
    character: Character;
    motion: number;
    genre: string;
    feel: boolean;
    feelIntensity: number;
    dirty: boolean;
    busy: boolean;
    canRerender: boolean;
    onapply: () => void;
    onplan: (p: Plan) => void;
    onrerenderplan: () => void;
    onclose: () => void;
    onplay: () => void;
    onside: (s: Side) => void;
    onblindtest: () => void;
  } = $props();

  let loop: LoopRegion | null = $state(null);
  let solo: string[] = $state([]);
  let muted: string[] = $state([]);
  let StageView: typeof import("./StageView.svelte").default | null = $state(null);
  let stageOpen = $state(false);
  let parts = $derived(player.stemNames.sort((a, b) => (a === "low_end" ? 1 : b === "low_end" ? -1 : a.localeCompare(b))));

  async function openStage() {
    stageOpen = !stageOpen;
    if (stageOpen && !StageView) StageView = (await import("./StageView.svelte")).default;
  }

  function setLoop(a: number, b: number) {
    loop = clampLoop(a, b, player.duration);
    void player.setLoop(loop);
  }

  function toggle(list: "solo" | "muted", name: string) {
    if (list === "solo") solo = solo.includes(name) ? solo.filter((n) => n !== name) : [...solo, name];
    else muted = muted.includes(name) ? muted.filter((n) => n !== name) : [...muted, name];
    if (!solo.length && !muted.length) player.useFullRender();
    else player.setStemMix({ solo, muted });
  }
</script>

<div class="np">
  <div class="backdrop" aria-hidden="true">
    {#if artworkUrl}<img src={artworkUrl} alt="" />{/if}
  </div>

  <header class="bar">
    <button class="btn icon ghost" type="button" onclick={onclose} aria-label="Minimise the player"><Icon name="chevron-down" /></button>
    <span class="eyebrow">Now playing</span>
    <GuardBadge {report} />
  </header>

  <div class="art">
    {#if artworkUrl}
      <img src={artworkUrl} alt={`Cover of ${title}`} />
    {:else}
      <div class="brand-art"><Logo size={96} title="" /></div>
    {/if}
  </div>

  <div class="titles">
    <h2>{title}</h2>
    {#if artist}<p class="muted">{artist}</p>{/if}
  </div>

  <ABSwitch {side} onchange={onside} />

  <div class="scrub">
    <Waveform {channels} duration={player.duration} {time} {loop} onseek={(t) => void player.seek(t)} onloop={setLoop} />
    <div class="times faint"><span>{formatTime(time)}</span><span>{formatTime(player.duration)}</span></div>
  </div>

  <div class="transport">
    <button class="btn icon" type="button" onclick={() => void player.seek(Math.max(0, time - 5))} aria-label="Back 5 seconds"><Icon name="back" /></button>
    <button class="play" type="button" onclick={onplay} aria-label={playing ? "Pause" : "Play"}><Icon name={playing ? "pause" : "play"} size={30} /></button>
    <button class="btn icon" type="button" class:on={!!loop} onclick={() => { loop = null; void player.setLoop(null); }} aria-label={loop ? "Clear the loop" : "Drag on the waveform to loop a part"} disabled={!loop}><Icon name="loop" /></button>
  </div>
  <p class="hint faint"><Icon name="headphones" size={16} /> Headphones on. Drag across the waveform to loop a passage.</p>

  <section class="card glass">
    <SceneControls bind:space bind:character bind:motion bind:genre detected={detectedGenre} {dirty} {busy} canApply={canRerender} {onapply} />
  </section>

  {#if plan}
    <section class="card glass">
      <button class="row-btn" type="button" aria-expanded={stageOpen} onclick={openStage}>
        <Icon name="stage" /> <span>The stage</span> <span class="faint">see every part around you, move them</span>
        <Icon name={stageOpen ? "chevron-up" : "chevron-down"} />
      </button>
      {#if stageOpen && StageView}
        <StageView {plan} {levels} {time} busy={busy || !canRerender} onchange={onplan} onrerender={onrerenderplan} />
      {/if}
    </section>
  {/if}

  {#if parts.length}
    <section class="card glass">
      <p class="eyebrow">Parts</p>
      <ul class="parts">
        {#each parts as name (name)}
          <li>
            <span>{STEM_LABELS[name] ?? name}</span>
            <button type="button" class="mini" aria-pressed={solo.includes(name)} onclick={() => toggle("solo", name)}>Solo</button>
            <button type="button" class="mini" aria-pressed={muted.includes(name)} onclick={() => toggle("muted", name)}>Mute</button>
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  {#if canVibrate()}
    <section class="card glass">
      <div class="row">
        <span><Icon name="pulse" /></span>
        <label for="feel" class="grow">Feel the kick <span class="faint">(vibration on the beat)</span></label>
        <input id="feel" type="checkbox" bind:checked={feel} />
      </div>
      {#if feel}
        <label class="field-label" for="feel-int">Intensity <span class="value">{Math.round(feelIntensity * 100)} percent</span></label>
        <input id="feel-int" type="range" min="0.1" max="1" step="0.05" bind:value={feelIntensity} style:--fill={`${feelIntensity * 100}%`} />
      {/if}
    </section>
  {/if}

  <section class="card glass">
    <button class="row-btn" type="button" onclick={onblindtest}><Icon name="flask" /> <span>Blind test</span> <span class="faint">compare without knowing which is which</span></button>
  </section>

  {#if downloads.length}
    <section class="downloads">
      {#each downloads as d (d.file)}
        <a class="btn" href={d.url} download={d.file}><Icon name="download" size={18} /> {d.label}</a>
      {/each}
    </section>
  {/if}
</div>

<style>
  .np {
    position: relative;
    display: grid;
    gap: var(--gap-5);
    padding-bottom: var(--gap-6);
  }

  .backdrop {
    position: fixed;
    inset: 0;
    z-index: -1;
    overflow: hidden;
    background: radial-gradient(90% 60% at 50% 0%, color-mix(in srgb, var(--accent) 28%, transparent), transparent 70%), var(--ink);
  }

  .backdrop img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    filter: blur(60px) saturate(140%) brightness(0.45);
    transform: scale(1.3);
  }

  .bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .art {
    width: min(78vw, 340px);
    aspect-ratio: 1;
    margin: 0 auto;
    border-radius: var(--radius-lg);
    overflow: hidden;
    box-shadow: var(--shadow-2);
  }

  .art img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .brand-art {
    width: 100%;
    height: 100%;
    display: grid;
    place-items: center;
    background:
      radial-gradient(70% 70% at 30% 20%, rgb(31 200 180 / 0.35), transparent 60%),
      radial-gradient(60% 60% at 80% 90%, rgb(255 122 92 / 0.3), transparent 60%),
      var(--ink-3);
  }

  .titles {
    text-align: center;
  }

  .titles h2 {
    font-size: var(--text-xl);
    overflow-wrap: anywhere;
  }

  .times {
    display: flex;
    justify-content: space-between;
    font-size: var(--text-xs);
    margin-top: 4px;
  }

  .transport {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: var(--gap-6);
  }

  .play {
    width: 72px;
    height: 72px;
    border-radius: 50%;
    border: 0;
    background: var(--ivory);
    color: var(--ink);
    display: grid;
    place-items: center;
    cursor: pointer;
    box-shadow: var(--shadow-2);
  }

  .hint {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 6px;
    font-size: var(--text-xs);
    text-align: center;
  }

  .card {
    padding: var(--gap-5);
    border-radius: var(--radius-lg);
    display: grid;
    gap: var(--gap-4);
  }

  .row-btn {
    display: flex;
    align-items: center;
    gap: var(--gap-3);
    width: 100%;
    min-height: 44px;
    border: 0;
    background: transparent;
    text-align: left;
    cursor: pointer;
    flex-wrap: wrap;
  }

  .row-btn .faint {
    flex: 1;
    font-size: var(--text-sm);
  }

  .parts {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--gap-2);
  }

  .parts li {
    display: grid;
    grid-template-columns: 1fr auto auto;
    align-items: center;
    gap: var(--gap-2);
    font-size: var(--text-sm);
  }

  .mini {
    min-height: 36px;
    min-width: 56px;
    border-radius: var(--radius-pill);
    border: 1px solid var(--hairline);
    background: transparent;
    font-size: var(--text-xs);
    font-weight: 600;
    cursor: pointer;
  }

  .mini[aria-pressed="true"] {
    background: var(--accent);
    color: var(--accent-ink);
    border-color: transparent;
  }

  .row {
    display: flex;
    align-items: center;
    gap: var(--gap-3);
  }

  .grow {
    flex: 1;
  }

  input[type="checkbox"] {
    width: 22px;
    height: 22px;
    accent-color: var(--lagoon);
  }

  .downloads {
    display: flex;
    flex-wrap: wrap;
    gap: var(--gap-2);
    justify-content: center;
  }
</style>
