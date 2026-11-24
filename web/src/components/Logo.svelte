<script lang="ts">
  // The SoundStage mark: a stage arc made of concentric sound fronts opening upward around the
  // listener (the dot). The innermost front is lagoon; the outer two are ivory, fading out.
  let { size = 28, title = "SoundStage" }: { size?: number; title?: string } = $props();
</script>

<svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label={title}>
  <path d="M9.5 21a6.5 6.5 0 0 1 13 0" fill="none" stroke="var(--lagoon)" stroke-width="2.2" stroke-linecap="round" />
  <path d="M5.5 21a10.5 10.5 0 0 1 21 0" fill="none" stroke="var(--ivory)" stroke-opacity="0.78" stroke-width="2" stroke-linecap="round" />
  <path d="M1.75 21a14.25 14.25 0 0 1 28.5 0" fill="none" stroke="var(--ivory)" stroke-opacity="0.38" stroke-width="1.8" stroke-linecap="round" />
  <circle cx="16" cy="21" r="2.2" fill="var(--coral)" />
</svg>
