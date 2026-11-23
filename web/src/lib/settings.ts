// The backend URL comes from the build (VITE_BACKEND_URL) and can be overridden per browser, so the
// same deployed page can point at a laptop on the Wi-Fi or at the Space without a rebuild.

const STORAGE_KEY = "soundstage.backendUrl";
export const BUILD_DEFAULT_BACKEND =
  (import.meta.env?.VITE_BACKEND_URL as string | undefined)?.trim() || "http://127.0.0.1:7860";

export type KeyValueStore = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function browserStorage(): KeyValueStore | null {
  // localStorage throws in some private modes and when site data is blocked.
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** Trim, add http:// when no scheme was typed, drop trailing slashes. Throws on nonsense. */
export function normaliseBackendUrl(raw: string): string {
  let value = raw.trim();
  if (!value) throw new Error("Enter the backend address, for example http://127.0.0.1:7860");
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) value = `http://${value}`;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`"${raw}" is not a web address`);
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("The backend address must start with http:// or https://");
  }
  return `${url.origin}${url.pathname}`.replace(/\/+$/, "");
}

export function loadBackendUrl(store: KeyValueStore | null = browserStorage()): string {
  try {
    const saved = store?.getItem(STORAGE_KEY);
    if (saved) return normaliseBackendUrl(saved);
  } catch {
    // A corrupt saved value falls back to the build default rather than breaking the page.
  }
  return normaliseBackendUrl(BUILD_DEFAULT_BACKEND);
}

export function saveBackendUrl(raw: string, store: KeyValueStore | null = browserStorage()): string {
  const url = normaliseBackendUrl(raw);
  try {
    if (url === normaliseBackendUrl(BUILD_DEFAULT_BACKEND)) store?.removeItem(STORAGE_KEY);
    else store?.setItem(STORAGE_KEY, url);
  } catch {
    // Not persisted, but still used for this visit.
  }
  return url;
}
