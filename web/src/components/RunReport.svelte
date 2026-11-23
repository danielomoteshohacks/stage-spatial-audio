<script lang="ts">
  import type { RunReport } from "../lib/api";
  import { formatDuration } from "../lib/format";
  import { profileInfo, STAGE_LABELS } from "../lib/labels";
  import Icon from "./Icon.svelte";

  let { report, notes = [] }: { report: RunReport; notes?: string[] } = $props();

  let total = $derived(report.stages.reduce((a, s) => a + s.duration_s, 0));
  let audioSeconds = $derived(report.input.duration_s ?? 0);
  let snr = $derived(
    report.separation
      ? report.separation.residual_snr_db === null
        ? "exact (no residual)"
        : `${report.separation.residual_snr_db.toFixed(1)} dB`
      : null,
  );
</script>

<section class="card report" aria-labelledby="report-title">
  <div>
    <p class="eyebrow">Run report</p>
    <h2 id="report-title" class="section-title">What ran</h2>
  </div>

  {#if report.fallback}
    <div class="notice warn" role="note">
      <Icon name="alert" size={18} />
      <div>
        <strong>Stems were asked for, but this is a Lite render of the whole mix.</strong>
        <p>Separation did not run: {report.fallback.reason}</p>
      </div>
    </div>
  {/if}

  <dl class="facts">
    <div><dt>Mode</dt><dd>{report.mode === "stems" ? "Stems" : "Lite"}{report.requested_mode !== report.mode ? ` (asked: ${report.requested_mode})` : ""}</dd></div>
    <div><dt>Profile</dt><dd>{profileInfo(report.profile).label} <code>{report.profile}</code></dd></div>
    <div><dt>Width</dt><dd><code>beta {report.beta.toFixed(2)}</code></dd></div>
    <div><dt>Excerpt</dt><dd>{report.input.start_s.toFixed(1)} s, {audioSeconds.toFixed(1)} s long{report.input.sample_rate ? `, ${report.input.sample_rate} Hz` : ""}</dd></div>
    {#if report.separation}
      <div><dt>Separation</dt><dd><code>{report.separation.model}</code> on {report.separation.device}</dd></div>
      <div><dt>Residual SNR</dt><dd>{snr}</dd></div>
    {/if}
    {#if report.levels}
      <div><dt>Loudness</dt><dd>matched to the original, {report.levels.spatial_rms_dbfs?.toFixed(1)} dBFS RMS</dd></div>
      {#if report.levels.peak_limited}
        <div><dt>Peak safety</dt><dd>{report.levels.peak_gain_db.toFixed(2)} dB, so the spatial side is this much quieter</dd></div>
      {/if}
    {/if}
  </dl>

  <table>
    <caption class="sr-only">Stage timings</caption>
    <thead><tr><th scope="col">Stage</th><th scope="col">Status</th><th scope="col" class="num">Time</th></tr></thead>
    <tbody>
      {#each report.stages as s (s.name)}
        <tr class={s.status}>
          <th scope="row">{STAGE_LABELS[s.name] ?? s.name}</th>
          <td>{s.status}</td>
          <td class="num">{s.status === "skipped" ? "" : formatDuration(s.duration_s)}</td>
        </tr>
      {/each}
    </tbody>
    <tfoot>
      <tr><th scope="row">Total</th><td>{audioSeconds && total ? `${(audioSeconds / total).toFixed(1)}x real time` : ""}</td><td class="num">{formatDuration(total)}</td></tr>
    </tfoot>
  </table>

  {#if notes.length}
    <ul class="notes faint">
      {#each notes as n (n)}<li>{n}</li>{/each}
    </ul>
  {/if}
  <p class="faint">SoundStage {report.stage_version}. These are timings and levels, not a judgement of how it sounds: your ears decide.</p>
</section>

<style>
  .report {
    display: grid;
    gap: 16px;
  }
  .notice p {
    margin-top: 4px;
    color: var(--text-2);
    word-break: break-word;
  }
  .facts {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
    margin: 0;
  }
  .facts div {
    padding: 12px 14px;
    border-radius: var(--radius-sm);
    background: var(--bg);
    border: 1px solid var(--line);
  }
  dt {
    font-size: 12px;
    color: var(--text-3);
    font-weight: 650;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }
  dd {
    margin: 4px 0 0;
    font-weight: 600;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
  }
  th,
  td {
    text-align: left;
    padding: 10px 0;
    border-bottom: 1px solid var(--line);
    font-weight: 500;
  }
  thead th {
    color: var(--text-3);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }
  tfoot th,
  tfoot td {
    border-bottom: 0;
    font-weight: 700;
  }
  .num {
    text-align: right;
    font-family: var(--mono);
  }
  tr.failed td {
    color: var(--danger);
  }
  tr.skipped td {
    color: var(--text-3);
  }
  .notes {
    margin: 0;
    padding-left: 18px;
  }
</style>
