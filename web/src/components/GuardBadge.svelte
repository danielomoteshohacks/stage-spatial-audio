<script lang="ts">
  // The fidelity guard's verdict as a small, honest badge; its reasons open on tap.
  import type { GuardReport } from "../lib/api";

  let { report }: { report: GuardReport | null | undefined } = $props();
  let open = $state(false);
  const WORDS = { pass: "Faithful", review: "Listen closely", fail: "Not faithful" } as const;
</script>

{#if report}
  <div class="badge-wrap">
    <button type="button" class={`badge ${report.verdict}`} aria-expanded={open} onclick={() => (open = !open)}>
      <span class="dot" aria-hidden="true"></span>
      {WORDS[report.verdict]}
    </button>
    {#if open}
      <div class="reasons glass" role="note">
        <p class="eyebrow">Fidelity guard</p>
        <ul>
          {#each report.reasons as r (r)}
            <li>{r}</li>
          {/each}
        </ul>
        <p class="faint small">
          Loudness {report.loudness_lufs.render.toFixed(1)} LUFS against {report.loudness_lufs.original.toFixed(1)};
          bass correlation {report.low_end_corr.toFixed(3)}.
        </p>
      </div>
    {/if}
  </div>
{/if}

<style>
  .badge-wrap {
    position: relative;
  }

  .badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 32px;
    padding: 0 12px;
    border-radius: var(--radius-pill);
    border: 1px solid var(--hairline);
    background: rgb(8 9 13 / 0.45);
    font-size: var(--text-xs);
    font-weight: 600;
    letter-spacing: 0.04em;
    cursor: pointer;
  }

  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
  }

  .pass .dot { background: var(--pass); }
  .review .dot { background: var(--review); }
  .fail .dot { background: var(--fail); }

  .reasons {
    position: absolute;
    z-index: 5;
    right: 0;
    top: 40px;
    width: min(320px, 86vw);
    padding: var(--gap-4);
    border-radius: var(--radius-md);
    font-size: var(--text-sm);
  }

  ul {
    margin: var(--gap-2) 0;
    padding-left: 1.1em;
  }

  .small {
    font-size: var(--text-xs);
  }
</style>
