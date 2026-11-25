<script lang="ts">
  // Four places: Home, Browse, Library, Create. A bottom bar of translucent glass on a phone and
  // a left rail from 900 px, the way a streaming app does it, with the wordmark and the theme
  // switch in the rail.
  import Icon, { type IconName } from "./Icon.svelte";
  import Logo from "./Logo.svelte";
  import type { ThemeChoice } from "../lib/theme";

  export type Tab = "home" | "browse" | "library" | "create";
  let {
    tab,
    theme,
    onselect,
    ontheme,
    oncredits,
  }: {
    tab: Tab;
    theme: ThemeChoice;
    onselect: (t: Tab) => void;
    ontheme: () => void;
    oncredits: () => void;
  } = $props();

  const TABS: { id: Tab; label: string; icon: IconName }[] = [
    { id: "home", label: "Home", icon: "home" },
    { id: "browse", label: "Browse", icon: "compass" },
    { id: "library", label: "Library", icon: "library" },
    { id: "create", label: "Create", icon: "plus" },
  ];
  const themeLabel = $derived(
    theme === "system" ? "Theme: follows the system" : theme === "light" ? "Theme: light" : "Theme: dark",
  );
</script>

<nav class="nav glass" aria-label="Main">
  <div class="brand"><Logo size={28} /><span>SoundStage</span></div>
  <ul>
    {#each TABS as t (t.id)}
      <li>
        <button type="button" aria-current={tab === t.id ? "page" : undefined} onclick={() => onselect(t.id)}>
          <Icon name={t.icon} size={22} />
          <span>{t.label}</span>
        </button>
      </li>
    {/each}
  </ul>
  <div class="foot">
    <button type="button" class="aux" onclick={ontheme} aria-label={themeLabel} title={themeLabel}>
      <Icon name={theme === "dark" ? "moon" : theme === "light" ? "sun" : "spatial"} size={20} />
      <span>{theme === "system" ? "Auto" : theme === "light" ? "Light" : "Dark"}</span>
    </button>
    <button type="button" class="aux" onclick={oncredits}>
      <Icon name="info" size={20} /><span>Credits</span>
    </button>
  </div>
</nav>

<style>
  .nav {
    position: fixed;
    z-index: 30;
    left: 0;
    right: 0;
    bottom: 0;
    height: calc(var(--nav-h) + env(safe-area-inset-bottom));
    padding-bottom: env(safe-area-inset-bottom);
    border-width: 1px 0 0;
    display: grid;
  }
  .brand,
  .foot {
    display: none;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(4, 1fr);
  }
  li button {
    width: 100%;
    height: var(--nav-h);
    display: grid;
    place-items: center;
    align-content: center;
    gap: 2px;
    border: 0;
    background: transparent;
    color: var(--text-2);
    font-size: 0.6875rem;
    font-weight: 600;
    transition: color var(--dur-1) var(--ease), transform var(--dur-2) var(--spring);
  }
  li button:active {
    transform: scale(0.92);
  }
  li button[aria-current="page"] {
    color: var(--accent);
  }
  @media (min-width: 900px) {
    .nav {
      top: 0;
      right: auto;
      width: var(--nav-w);
      height: auto;
      padding: var(--gap-5) var(--gap-3);
      border-width: 0 1px 0 0;
      grid-template-rows: auto 1fr auto;
      align-content: start;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: var(--gap-3);
      padding: 0 var(--gap-3) var(--gap-5);
      font-family: var(--font-display);
      font-size: var(--text-lg);
    }
    ul {
      grid-template-columns: 1fr;
      gap: 2px;
      align-content: start;
    }
    li button {
      height: 48px;
      grid-auto-flow: column;
      justify-content: start;
      place-items: center start;
      gap: var(--gap-3);
      padding: 0 var(--gap-3);
      font-size: var(--text-md);
      border-radius: var(--radius-sm);
    }
    li button[aria-current="page"] {
      background: var(--accent-soft);
    }
    .foot {
      display: grid;
      gap: 2px;
    }
    .aux {
      display: flex;
      align-items: center;
      gap: var(--gap-3);
      height: 44px;
      padding: 0 var(--gap-3);
      border: 0;
      background: transparent;
      color: var(--text-2);
      font-weight: 600;
      border-radius: var(--radius-sm);
    }
    .aux:hover {
      background: var(--surface-2);
    }
  }
</style>
