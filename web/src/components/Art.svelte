<script lang="ts">
  // Album art: the picture when there is one, otherwise a soft gradient from the track's own
  // colours, so no surface is ever blank. The picture loads lazily and decodes off the main thread.
  import { hashTint, tintStyle } from "../lib/tint";

  let {
    id,
    src = "",
    size = 56,
    radius = 12,
    label = "",
    eager = false,
  }: { id: string; src?: string; size?: number; radius?: number; label?: string; eager?: boolean } = $props();
  let failed = $state(false);
  const style = $derived(tintStyle(hashTint(id)));
</script>

<span class="art" style="{style};--s:{size}px;--r:{radius}px" role={label ? "img" : undefined} aria-label={label || undefined}>
  {#if src && !failed}
    <img {src} alt="" width={size} height={size} loading={eager ? "eager" : "lazy"} fetchpriority={eager ? "high" : "auto"} decoding="async" onerror={() => (failed = true)} />
  {/if}
</span>

<style>
  .art {
    display: block;
    flex: none;
    width: var(--s);
    height: var(--s);
    border-radius: var(--r);
    overflow: hidden;
    background:
      linear-gradient(180deg, rgb(255 255 255 / 0.22), transparent 45%),
      linear-gradient(145deg, var(--tint-1), var(--tint-2));
    box-shadow: var(--shadow-1), inset 0 0 0 1px rgb(0 0 0 / 0.06);
  }
  img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
</style>
