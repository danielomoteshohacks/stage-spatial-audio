// Light by default (even when the system is dark), dark when the listener chooses it or, with the setting on "system", when the
// system asks for it. The choice is stored on this device only. `?theme=dark` forces a theme for
// one visit (used by the screenshot and Lighthouse runs); it is never stored.

export type ThemeChoice = "system" | "light" | "dark";
export type Theme = "light" | "dark";

const KEY = "soundstage.theme";

export function isChoice(v: unknown): v is ThemeChoice {
  return v === "system" || v === "light" || v === "dark";
}

/** The theme that applies for a choice, given whether the system prefers dark. */
export function resolveTheme(choice: ThemeChoice, systemDark: boolean): Theme {
  if (choice === "system") return systemDark ? "dark" : "light";
  return choice;
}

export function loadChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    // Light unless the listener picked otherwise: the owner wants white as the default look, so a
    // phone in system dark mode still opens light until "Dark" or "System" is chosen in Credits.
    return isChoice(v) ? v : "light";
  } catch {
    return "light";
  }
}

export function saveChoice(choice: ThemeChoice): void {
  try {
    localStorage.setItem(KEY, choice);
  } catch {
    // Private windows can refuse storage; the choice then lasts for this visit only.
  }
}

export function forcedTheme(search: string): Theme | null {
  const v = new URLSearchParams(search).get("theme");
  return v === "dark" || v === "light" ? v : null;
}

/** Colour of the browser's address bar for a theme. */
export const THEME_COLOR: Record<Theme, string> = { light: "#faf8f5", dark: "#15161b" };

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLOR[theme]);
}

/** Resolve and apply the theme now, and again when the system's preference changes. */
export function initTheme(choice: ThemeChoice): () => void {
  const forced = forcedTheme(location.search);
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  const run = () => applyTheme(forced ?? resolveTheme(choice, mq.matches));
  run();
  mq.addEventListener("change", run);
  return () => mq.removeEventListener("change", run);
}
