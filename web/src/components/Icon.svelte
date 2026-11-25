<script lang="ts">
  // One icon set on a 24 px grid, 1.75 px round strokes, no fills (play and pause excepted, which
  // are solid so they read at small sizes). Decorative by default; pass `label` to announce one.
  export type IconName =
    | "play" | "pause" | "upload" | "close" | "chevron-up" | "chevron-down" | "loop" | "info"
    | "settings" | "stage" | "pulse" | "check" | "alert" | "download" | "refresh" | "headphones"
    | "trash" | "flask" | "move" | "back" | "minus" | "home" | "compass" | "library" | "plus"
    | "queue" | "next" | "prev" | "sun" | "moon" | "search" | "spatial" | "list" | "ear";

  let { name, size = 20, label }: { name: IconName; size?: number; label?: string } = $props();

  const PATHS: Record<IconName, string> = {
    play: "M8 5.5v13l10.5-6.5z",
    pause: "M7 5h3.5v14H7zM13.5 5H17v14h-3.5z",
    upload: "M12 16V4M7 9l5-5 5 5M5 15v3a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3",
    close: "M6 6l12 12M18 6L6 18",
    "chevron-up": "M6 15l6-6 6 6",
    "chevron-down": "M6 9l6 6 6-6",
    loop: "M17 3l3 3-3 3M4 11V9a3 3 0 0 1 3-3h13M7 21l-3-3 3-3M20 13v2a3 3 0 0 1-3 3H4",
    info: "M12 11v6M12 7.5v.01M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z",
    settings: "M4 7h10M18 7h2M4 17h4M12 17h8M16 5v4M10 15v4",
    stage: "M4 17a8 8 0 0 1 16 0M7.5 17a4.5 4.5 0 0 1 9 0M12 17v.01M2 21h20",
    pulse: "M3 12h4l2-6 4 12 2-6h6",
    check: "M5 12.5l4.5 4.5L19 7.5",
    alert: "M12 8v5M12 16.5v.01M10.3 3.9L2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
    download: "M12 4v12M7 11l5 5 5-5M5 20h14",
    refresh: "M20 11a8 8 0 0 0-14.3-4.9L4 8M4 4v4h4M4 13a8 8 0 0 0 14.3 4.9L20 16M20 20v-4h-4",
    headphones: "M4 16v-3a8 8 0 0 1 16 0v3M4 16a2 2 0 0 0 2 2h1v-6H6a2 2 0 0 0-2 2zM20 16a2 2 0 0 1-2 2h-1v-6h1a2 2 0 0 1 2 2z",
    trash: "M5 7h14M10 7V5h4v2M7 7l1 13h8l1-13",
    flask: "M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4a2 2 0 0 0 1.8-3l-5-9V3M7.5 15h9",
    move: "M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3",
    back: "M15 6l-6 6 6 6",
    minus: "M6 12h12",
    home: "M4 11l8-7 8 7M6 9.5V20h12V9.5M10 20v-6h4v6",
    compass: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM15.5 8.5l-2 5-5 2 2-5z",
    library: "M5 4v16M10 4v16M15.5 5l3.5 14M3 20h18",
    plus: "M12 5v14M5 12h14",
    queue: "M4 7h12M4 12h12M4 17h7M18 14v6M15 17h6",
    next: "M6 5.5v13l8-6.5zM17 5v14",
    prev: "M18 5.5v13l-8-6.5zM7 5v14",
    sun: "M12 16.5a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9zM12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4",
    moon: "M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z",
    search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4",
    spatial: "M12 12m-1.5 0a1.5 1.5 0 1 0 3 0a1.5 1.5 0 1 0-3 0M7.5 7.5a6.4 6.4 0 0 0 0 9M16.5 7.5a6.4 6.4 0 0 1 0 9M4.5 4.5a10.6 10.6 0 0 0 0 15M19.5 4.5a10.6 10.6 0 0 1 0 15",
    list: "M8 6h12M8 12h12M8 18h12M4 6v.01M4 12v.01M4 18v.01",
    ear: "M7 10a5 5 0 0 1 10 0c0 3-3 3.5-3 6.5a2.5 2.5 0 0 1-5 0M10 10a2 2 0 0 1 4 0",
  };
  const SOLID = new Set<IconName>(["play", "pause", "next", "prev"]);
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  role={label ? "img" : undefined}
  aria-label={label}
  aria-hidden={label ? undefined : "true"}
  class="icon"
>
  {#if SOLID.has(name)}
    <path d={PATHS[name]} fill="currentColor" />
  {:else}
    <path d={PATHS[name]} fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" />
  {/if}
</svg>

<style>
  .icon {
    flex: none;
    display: block;
  }
</style>
