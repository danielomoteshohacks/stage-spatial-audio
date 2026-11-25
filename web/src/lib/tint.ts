// A pair of colours for a track, so every album surface has its own gradient even when the cover
// art cannot be read (a remote image without CORS headers cannot be sampled). Deterministic from
// the track id: the same track always has the same colours, in both themes (the surfaces mix them
// with the theme's own background, so they stay soft in light and deep in dark).

export interface Tint {
  t1: string;
  t2: string;
}

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function hashTint(id: string): Tint {
  const h = hash(id);
  const hue = h % 360;
  const hue2 = (hue + 40 + ((h >> 9) % 80)) % 360;
  return { t1: `hsl(${hue} 62% 52%)`, t2: `hsl(${hue2} 58% 46%)` };
}

export function tintStyle(t: Tint): string {
  return `--tint-1:${t.t1};--tint-2:${t.t2}`;
}
