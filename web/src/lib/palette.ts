// Colours for the now-playing screen from the cover art, the way music apps tint the player.
// Loaded lazily (it is only needed once a track with artwork is open).
//
// Method: draw the image at 40 x 40, bucket pixels by hue (24 buckets) after dropping near-grey
// and near-black pixels, score each bucket by count times mean saturation, and take the two best
// buckets at least 40 degrees of hue apart. Each colour's lightness is raised until it reaches
// 4.5:1 contrast on the ink background, so tinted text and controls stay readable.

export interface Palette {
  accent: string;
  accent2: string;
  /** A dark tint for the backdrop gradient behind the blurred artwork. */
  base: string;
}

const INK = [8, 9, 13];

function luminance([r, g, b]: number[]): number {
  const f = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

export function contrast(a: number[], b: number[]): number {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

export function rgbToHsl([r, g, b]: number[]): [number, number, number] {
  const rr = r / 255, gg = g / 255, bb = b / 255;
  const max = Math.max(rr, gg, bb), min = Math.min(rr, gg, bb);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h = max === rr ? (gg - bb) / d + (gg < bb ? 6 : 0) : max === gg ? (bb - rr) / d + 2 : (rr - gg) / d + 4;
  h *= 60;
  return [h, s, l];
}

export function hslToRgb([h, s, l]: number[]): number[] {
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return [r, g, b].map((v) => Math.round((v + m) * 255));
}

const hex = (rgb: number[]) => "#" + rgb.map((v) => v.toString(16).padStart(2, "0")).join("");

/** Raise lightness (keeping hue and some saturation) until the colour reads on ink. */
export function readable(rgb: number[], min = 4.5): number[] {
  const hsl = rgbToHsl(rgb);
  const h = hsl[0];
  let [, s, l] = hsl;
  s = Math.min(Math.max(s, 0.45), 0.85);
  let out = hslToRgb([h, s, l]);
  while (contrast(out, INK) < min && l < 0.92) {
    l += 0.02;
    out = hslToRgb([h, s, l]);
  }
  return out;
}

/** Palette from RGBA pixel data (exported for tests). */
export function paletteFromPixels(data: Uint8ClampedArray): Palette | null {
  const buckets = Array.from({ length: 24 }, () => ({ n: 0, s: 0, r: 0, g: 0, b: 0 }));
  for (let i = 0; i < data.length; i += 4) {
    const rgb = [data[i], data[i + 1], data[i + 2]];
    const [h, s, l] = rgbToHsl(rgb);
    if (s < 0.18 || l < 0.08 || l > 0.95) continue;
    const k = Math.floor(h / 15) % 24;
    const bk = buckets[k];
    bk.n++;
    bk.s += s;
    bk.r += rgb[0];
    bk.g += rgb[1];
    bk.b += rgb[2];
  }
  const ranked = buckets
    .map((bk, k) => ({ k, score: bk.n * (bk.n ? bk.s / bk.n : 0), rgb: bk.n ? [bk.r / bk.n, bk.g / bk.n, bk.b / bk.n].map(Math.round) : [0, 0, 0] }))
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score);
  if (!ranked.length) return null;
  const first = ranked[0];
  const second = ranked.find((x) => Math.min(Math.abs(x.k - first.k), 24 - Math.abs(x.k - first.k)) * 15 >= 40) ?? first;
  const [h, s] = rgbToHsl(first.rgb);
  return {
    accent: hex(readable(first.rgb)),
    accent2: hex(readable(second.rgb)),
    base: hex(hslToRgb([h, Math.min(s, 0.5), 0.12])),
  };
}

export async function extractPalette(url: string): Promise<Palette | null> {
  const img = new Image();
  img.decoding = "async";
  img.src = url;
  await img.decode();
  const size = 40;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;
  ctx.drawImage(img, 0, 0, size, size);
  return paletteFromPixels(ctx.getImageData(0, 0, size, size).data);
}
