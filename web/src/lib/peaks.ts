import type { BufferLike } from "./abPlayer";

export interface Peaks {
  /** Per-bucket minimum sample across all channels, in [-1, 1]. */
  min: Float32Array;
  /** Per-bucket maximum sample across all channels, in [-1, 1]. */
  max: Float32Array;
}

/** Reduce a buffer to `buckets` min/max pairs for drawing a waveform. */
export function computePeaks(buffer: BufferLike, buckets: number): Peaks {
  const n = Math.max(1, Math.floor(buckets));
  const min = new Float32Array(n);
  const max = new Float32Array(n);
  const len = buffer.length;
  if (len === 0) return { min, max };
  const channels = Array.from({ length: buffer.numberOfChannels }, (_, c) =>
    buffer.getChannelData(c),
  );
  for (let b = 0; b < n; b++) {
    const start = Math.floor((b * len) / n);
    const end = Math.max(start + 1, Math.floor(((b + 1) * len) / n));
    let lo = Infinity;
    let hi = -Infinity;
    for (const data of channels) {
      for (let i = start; i < end && i < len; i++) {
        const v = data[i] ?? 0;
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
    }
    min[b] = Number.isFinite(lo) ? Math.max(-1, lo) : 0;
    max[b] = Number.isFinite(hi) ? Math.min(1, hi) : 0;
  }
  return { min, max };
}
