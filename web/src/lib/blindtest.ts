// A blind A/B/C listening test: the conditions play in a random order under neutral letters,
// loudness-matched, and the listener ranks them and picks the one "most outside my head" and
// the one "most natural". Trials are kept in this browser and exported as CSV; nothing is sent.

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
  const head = ["trial", "at", "track", "order_A", "order_B", "order_C", "rank_1", "rank_2", "rank_3", "most_outside_head", "most_natural", "gains_db"];
  const esc = (v: string) => (/[",\n]/.test(v) ? `"${v.replaceAll('"', '""')}"` : v);
  const rows = trials.map((t) =>
    [String(t.trial), t.at, t.track, t.order[0] ?? "", t.order[1] ?? "", t.order[2] ?? "", t.ranking[0] ?? "", t.ranking[1] ?? "", t.ranking[2] ?? "", t.outside, t.natural,
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
