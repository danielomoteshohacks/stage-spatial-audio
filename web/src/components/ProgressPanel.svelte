<script lang="ts">
  // Live progress: the upload, then one row per backend stage as the stream reports it.
  import type { StageState } from "../lib/api";
  import { formatDuration } from "../lib/format";
  import { STAGE_LABELS } from "../lib/labels";
  import Icon from "./Icon.svelte";

  let {
    phase,
    upload,
    stages,
    oncancel,
  }: {
    phase: "uploading" | "processing" | "downloading";
    upload: number;
    stages: StageState[];
    oncancel: () => void;
  } = $props();

  let current = $derived(
    phase === "uploading"
      ? `Uploading, ${Math.round(upload * 100)} percent`
      : phase === "downloading"
        ? "Bringing the renders to your phone"
        : (STAGE_LABELS[stages.find((s) => s.status === "running")?.stage ?? ""] ?? "Waiting for the server"),
  );
</script>

<section class="progress glass" aria-labelledby="progress-title">
  <div class="head">
    <div>
      <p class="eyebrow">Building your stage</p>
      <h2 id="progress-title" aria-live="polite">{current}</h2>
    </div>
    <button type="button" class="btn" onclick={oncancel}>Cancel</button>
  </div>
  <ol>
    <li class:done={phase !== "uploading"} class:active={phase === "uploading"}>
      <span class="dot">{#if phase === "uploading"}<span class="spin"></span>{:else}<Icon name="check" size={14} />{/if}</span>
      <span>Uploading</span>
      <span class="time">{#if phase === "uploading"}<span class="bar"><span style:width={`${upload * 100}%`}></span></span>{/if}</span>
    </li>
    {#each stages.filter((s) => s.status !== "skipped" || s.stage !== "separate") as s (s.stage)}
      <li class:done={s.status === "ok"} class:active={s.status === "running"} class:failed={s.status === "failed"} class:skipped={s.status === "skipped"}>
        <span class="dot">
          {#if s.status === "running"}<span class="spin"></span>
          {:else if s.status === "ok"}<Icon name="check" size={14} />
          {:else if s.status === "failed"}<Icon name="close" size={14} />
          {:else if s.status === "skipped"}<Icon name="minus" size={14} />{/if}
        </span>
        <span>{STAGE_LABELS[s.stage] ?? s.stage}{#if s.status === "failed" && s.error}<span class="err">{s.error}</span>{/if}</span>
        <span class="time">{s.status === "ok" ? formatDuration(s.duration_s) : ""}</span>
      </li>
    {/each}
  </ol>
</section>

<style>
  .progress {
    padding: var(--gap-5);
    display: grid;
    gap: var(--gap-4);
  }

  .head {
    display: flex;
    justify-content: space-between;
    gap: var(--gap-4);
    align-items: flex-start;
  }

  h2 {
    font-size: var(--text-xl);
  }

  ol {
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
    gap: var(--gap-3);
    min-height: 36px;
    color: var(--ivory-3);
    font-size: var(--text-sm);
  }

  li.done,
  li.active {
    color: var(--ivory);
  }

  li.failed {
    color: var(--coral);
  }

  .dot {
    width: 22px;
    height: 22px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: rgb(244 241 234 / 0.06);
  }

  li.done .dot {
    background: var(--lagoon);
    color: var(--accent-ink);
  }

  .spin {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    border: 2px solid rgb(244 241 234 / 0.2);
    border-top-color: var(--lagoon);
    animation: spin 0.9s linear infinite;
  }

  .err {
    display: block;
    font-size: var(--text-xs);
  }

  .time {
    font-size: var(--text-xs);
    color: var(--ivory-3);
  }

  .bar {
    display: block;
    width: 72px;
    height: 4px;
    border-radius: 4px;
    background: rgb(244 241 234 / 0.12);
    overflow: hidden;
  }

  .bar span {
    display: block;
    height: 100%;
    background: var(--lagoon);
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>
