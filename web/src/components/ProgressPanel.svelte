<script lang="ts">
  import type { StageState } from "../lib/api";
  import { formatDuration } from "../lib/format";
  import { STAGE_LABELS } from "../lib/labels";
  import Icon from "./Icon.svelte";

  let {
    phase,
    upload,
    stages,
    mode,
    oncancel,
  }: {
    phase: "uploading" | "processing" | "downloading";
    upload: number;
    stages: StageState[];
    mode: string;
    oncancel: () => void;
  } = $props();

  let visible = $derived(stages.filter((s) => mode === "stems" || s.stage !== "separate" || s.status !== "pending"));
  let current = $derived(
    phase === "uploading"
      ? `Uploading, ${Math.round(upload * 100)} percent`
      : phase === "downloading"
        ? "Downloading the renders"
        : (STAGE_LABELS[stages.find((s) => s.status === "running")?.stage ?? ""] ?? "Waiting in the queue"),
  );
</script>

<section class="card progress rise" aria-labelledby="progress-title">
  <div class="head">
    <div>
      <p class="eyebrow">Working</p>
      <h2 id="progress-title" class="section-title" aria-live="polite">{current}</h2>
    </div>
    <button type="button" class="btn btn-sm" onclick={oncancel}>Cancel</button>
  </div>

  <ol class="steps">
    <li class:done={phase !== "uploading"} class:active={phase === "uploading"}>
      <span class="dot">
        {#if phase === "uploading"}<span class="spinner"></span>{:else}<Icon name="check" size={14} />{/if}
      </span>
      <span class="label">Uploading</span>
      <span class="time">
        {#if phase === "uploading"}
          <span class="bar" aria-hidden="true"><span style:width={`${upload * 100}%`}></span></span>
        {/if}
      </span>
    </li>
    {#each visible as s (s.stage)}
      <li class:done={s.status === "ok"} class:active={s.status === "running"} class:failed={s.status === "failed"} class:skipped={s.status === "skipped"}>
        <span class="dot">
          {#if s.status === "running"}<span class="spinner"></span>
          {:else if s.status === "ok"}<Icon name="check" size={14} />
          {:else if s.status === "failed"}<Icon name="x" size={14} />
          {:else if s.status === "skipped"}<Icon name="dash" size={14} />{/if}
        </span>
        <span class="label">
          {STAGE_LABELS[s.stage] ?? s.stage}
          {#if s.status === "failed" && s.error}<span class="error">{s.error}</span>{/if}
        </span>
        <span class="time">{s.status === "ok" || s.status === "failed" ? formatDuration(s.duration_s) : s.status === "skipped" ? "skipped" : ""}</span>
      </li>
    {/each}
    <li class:active={phase === "downloading"}>
      <span class="dot">{#if phase === "downloading"}<span class="spinner"></span>{/if}</span>
      <span class="label">Loading into the player</span>
      <span class="time"></span>
    </li>
  </ol>
</section>

<style>
  .progress {
    display: grid;
    gap: 18px;
  }
  .head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
  }
  .steps {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 2px;
  }
  li {
    display: grid;
    grid-template-columns: 28px 1fr auto;
    align-items: center;
    gap: 12px;
    min-height: 44px;
    color: var(--text-3);
  }
  li.active,
  li.done {
    color: var(--text);
  }
  li.failed {
    color: var(--danger);
  }
  .dot {
    display: grid;
    place-items: center;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    border: 1.5px solid var(--line-strong);
  }
  li.done .dot {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--accent-ink);
  }
  li.failed .dot {
    border-color: var(--danger);
  }
  li.active .dot {
    border-color: transparent;
  }
  .spinner {
    width: 22px;
    height: 22px;
    border-radius: 50%;
    border: 2px solid var(--surface-3);
    border-top-color: var(--accent);
    animation: spin 0.9s linear infinite;
  }
  .label {
    display: grid;
    font-weight: 600;
    font-size: 15px;
  }
  .error {
    font-weight: 400;
    font-size: 13px;
    color: var(--text-2);
    word-break: break-word;
  }
  .time {
    font-family: var(--mono);
    font-size: 13px;
    color: var(--text-3);
  }
  .bar {
    display: block;
    width: 72px;
    height: 4px;
    border-radius: 2px;
    background: var(--surface-3);
    overflow: hidden;
  }
  .bar span {
    display: block;
    height: 100%;
    background: var(--accent);
    transition: width 120ms linear;
  }
</style>
