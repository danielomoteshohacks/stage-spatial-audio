<script lang="ts">
  // The SoundStage mark: the listener (the dot) with two sound fronts turning around it, one from
  // the front-left and one from the back-right. Read together the two arcs make an S, and they
  // say what the product does: sound placed all around you, not in a line between the ears.
  // The fronts are drawn with a gradient from the spatial colour to the voice colour of the
  // player's orbit, so the mark and the player speak the same language.
  let { size = 28, title = "SoundStage" }: { size?: number; title?: string } = $props();
  const id = `ss-${Math.random().toString(36).slice(2, 8)}`;
</script>

<svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label={title}>
  <defs>
    <linearGradient id={id} x1="4" y1="4" x2="28" y2="28" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="var(--lagoon)" />
      <stop offset="1" stop-color="#ff6b6b" />
    </linearGradient>
  </defs>
  <!-- Upper front: from the left side over the top to the right, ending above the listener. -->
  <path d="M6 16 A10 10 0 0 1 26 13.5" fill="none" stroke="url(#{id})" stroke-width="3.2" stroke-linecap="round" />
  <!-- Lower front: the same turn mirrored through the listener, so the pair reads as an S. -->
  <path d="M26 16 A10 10 0 0 1 6 18.5" fill="none" stroke="url(#{id})" stroke-width="3.2" stroke-linecap="round" />
  <circle cx="16" cy="16" r="3" fill="currentColor" />
</svg>
