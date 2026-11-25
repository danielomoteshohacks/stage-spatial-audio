// A blind listening test: the conditions (the original, the v3 render and, if the listener loads
// one, a reference they obtained themselves) play in a random order under neutral letters,
// loudness-matched, and the listener ranks them and picks the one "most outside my head" and the
// one "most natural". Trials are kept in this browser and exported as CSV; nothing is sent.
//
// The reference slot exists because the comparison that matters is against what listeners already
// know. SoundStage does not ship, make or imitate any commercial format: the listener loads a
// binaural rendering of the same song from wherever they have it (an Atmos-style headphone
// rendering of a track they own or may use), and it is judged blind like the others. The file
// never leaves the browser, and its name is recorded in the CSV only so the listener can tell
// their own trials apart.

export interface Condition {
  id: string; // e.g. "original", "v2", "v1" (hidden from the listener until export)
  label: string;
  buffer: AudioBuffer;
}

export interface Trial {
  trial: number;
  at: string;
  track: string;
  order: string[]; // condition ids in the order shown as A, B, C
  ranking: string[]; // condition ids, best first
  outside: string;
  natural: string;
  gains_db: Record<string, number>;
  /** Name of the file loaded into the reference slot, if there was one. */
  reference_file?: string;
}

export const MAX_CONDITIONS = 4;
export const LETTERS = ["A", "B", "C", "D"];

/** Seconds that all buffers can loop over together, so the letters stay time-locked. */
export function commonLoopSeconds(buffers: { duration: number }[]): number {
  return buffers.length ? Math.min(...buffers.map((b) => b.duration)) : 0;
}

/** Order in which trials are presented the first time: reproducible only by the listener's
 * own CSV, never from a seed. A new array each call. */
export function balancedOrders(ids: string[]): string[][] {
  // Every cyclic rotation of a shuffle: each condition appears at each letter once over n trials,
  // which cancels position bias without making the next order predictable from the last one.
  const base = shuffle(ids);
  return base.map((_, k) => base.map((__, i) => base[(i + k) % base.length]));
}

/** Fisher-Yates with crypto randomness, so the order cannot be guessed from a seed. */
export function shuffle<T>(items: T[], rand: () => number = cryptoRandom): T[] {
  const a = [...items];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function cryptoRandom(): number {
  const u = new Uint32Array(1);
  crypto.getRandomValues(u);
  return u[0] / 2 ** 32;
}

/** RMS over all channels of the middle 80 percent (fade-ins and tails left out). */
export function rmsOf(channels: Float32Array[]): number {
  let sum = 0;
  let n = 0;
  for (const c of channels) {
    const a = Math.floor(c.length * 0.1);
    const b = Math.ceil(c.length * 0.9);
    for (let i = a; i < b; i++) {
      sum += c[i] * c[i];
      n++;
    }
  }
  return n ? Math.sqrt(sum / n) : 0;
}

/** Gain (linear) per condition that brings each to the quietest one's RMS: never louder. */
export function matchGains(levels: Record<string, number>): Record<string, number> {
  const quiet = Math.min(...Object.values(levels).filter((v) => v > 0));
  return Object.fromEntries(Object.entries(levels).map(([k, v]) => [k, v > 0 ? quiet / v : 1]));
}

export function toCsv(trials: Trial[]): string {
  const head = ["trial", "at", "track", ...LETTERS.map((l) => `order_${l}`), ...LETTERS.map((_, i) => `rank_${i + 1}`), "most_outside_head", "most_natural", "reference_file", "gains_db"];
  const esc = (v: string) => (/[",\n]/.test(v) ? `"${v.replaceAll('"', '""')}"` : v);
  const rows = trials.map((t) =>
    [String(t.trial), t.at, t.track, ...LETTERS.map((_, i) => t.order[i] ?? ""), ...LETTERS.map((_, i) => t.ranking[i] ?? ""), t.outside, t.natural, t.reference_file ?? "",
      Object.entries(t.gains_db).map(([k, v]) => `${k}:${v.toFixed(2)}`).join(" ")].map(esc).join(","),
  );
  return [head.join(","), ...rows].join("\n") + "\n";
}

const KEY = "soundstage.blindtest.v1";

export function loadTrials(): Trial[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]") as Trial[];
  } catch {
    return [];
  }
}

export function saveTrials(trials: Trial[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(trials));
  } catch {
    // Private mode or storage full: the trials stay in memory and can still be exported.
  }
}
