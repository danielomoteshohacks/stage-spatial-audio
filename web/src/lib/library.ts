// Recent renders, kept on this device in IndexedDB, so replaying one never re-uploads or
// re-downloads anything (mobile data). Each entry holds the original and spatial FLACs as
// received, the object stems, the artwork and the reports. At most MAX_ENTRIES are kept; the
// oldest goes first. Storage can be refused or cleared by the browser at any time, so every
// call fails soft and the app keeps working without it.

export interface LibraryEntry {
  id: string;
  name: string;
  title?: string;
  artist?: string;
  createdAt: number;
  original: Blob;
  spatial: Blob;
  objects: Record<string, Blob>;
  artwork?: Blob;
  run: unknown;
  report: unknown;
  plan: unknown;
  trackId: string | null;
  space: string;
  durationS: number;
}

export type LibrarySummary = Omit<LibraryEntry, "original" | "spatial" | "objects">;

const DB = "soundstage";
const STORE = "renders";
export const MAX_ENTRIES = 8;

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") return reject(new Error("no IndexedDB"));
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "id" }).createIndex("createdAt", "createdAt");
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return open().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const t = db.transaction(STORE, mode);
        const req = fn(t.objectStore(STORE));
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      }),
  );
}

export async function listRecent(): Promise<LibrarySummary[]> {
  try {
    const all = (await tx<LibraryEntry[]>("readonly", (s) => s.getAll())) ?? [];
    return all
      .sort((a, b) => b.createdAt - a.createdAt)
      .map(({ original: _o, spatial: _s, objects: _x, ...rest }) => rest);
  } catch {
    return [];
  }
}

export async function getEntry(id: string): Promise<LibraryEntry | null> {
  try {
    return (await tx<LibraryEntry | undefined>("readonly", (s) => s.get(id))) ?? null;
  } catch {
    return null;
  }
}

export async function removeEntry(id: string): Promise<void> {
  try {
    await tx("readwrite", (s) => s.delete(id));
  } catch {
    // Nothing to do: the entry was never stored or storage is gone.
  }
}

export async function saveEntry(entry: LibraryEntry): Promise<boolean> {
  try {
    // Ask once for persistent storage, so the browser does not evict renders under pressure.
    await navigator.storage?.persist?.();
    await tx("readwrite", (s) => s.put(entry));
    const all = await listRecent();
    for (const old of all.slice(MAX_ENTRIES)) await removeEntry(old.id);
    return true;
  } catch {
    return false;
  }
}
