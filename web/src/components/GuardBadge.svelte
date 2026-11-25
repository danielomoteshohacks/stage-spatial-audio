<script lang="ts">
  // The fidelity guard's verdict as a small, honest badge; its reasons open on tap. On a long song
  // the guard checks windows, and the badge says how much it covered.
  let {
    verdict,
    reasons = [],
    coverage,
  }: {
    verdict: "pass" | "review" | "fail" | null | undefined;
    reasons?: string[];
    coverage?: { analysed_s: number; song_s: number; full: boolean } | null;
  } = $props();
  let open = $state(false);
  const WORDS = { pass: "Faithful", review: "Listen closely", fail: "Not faithful" } as const;
</script>

{#if verdict}
  <div class="badge-wrap">
    <button type="button" class={`badge ${verdict}`} aria-expanded={open} onclick={() => (open = !open)}>
      <span class="dot" aria-hidden="true"></span>
      {WORDS[verdict]}
    </button>
    {#if open}
      <div class="reasons glossy" role="note">
        <p class="eyebrow">Fidelity guard</p>
        <ul>
          {#each reasons as r (r)}<li>{r}</li>{/each}
        </ul>
        {#if coverage && !coverage.full}
          <p class="small muted">
            Checked {Math.round(coverage.analysed_s)} s of {Math.round(coverage.song_s)} s in windows spread over
            the song, and its loudness and peak over all of it.
          </p>
        {/if}
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
    min-height: 36px;
    padding: 0 var(--gap-4);
    border-radius: var(--radius-pill);
    border: 1px solid var(--hairline-strong);
    background: var(--surface);
    font-weight: 600;
    font-size: var(--text-sm);
    box-shadow: var(--shadow-1);
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--pass);
  }
  .review .dot {
    background: var(--review);
  }
  .fail .dot {
    background: var(--fail);
  }
  .reasons {
    position: absolute;
    z-index: 5;
    top: calc(100% + 8px);
    left: 0;
    width: min(320px, 80vw);
    padding: var(--gap-4);
    display: grid;
    gap: var(--gap-2);
  }
  ul {
    margin: 0;
    padding-left: 1.1em;
    font-size: var(--text-sm);
  }
</style>
