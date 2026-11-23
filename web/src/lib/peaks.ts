/**
 * Peak envelope for drawing: the largest absolute sample over all channels in each of `buckets`
 * equal slices. Peaks rather than RMS so transients stay visible as landmarks for looping.
 */
export function computePeaks(channels: Float32Array[], buckets: number): Float32Array {
  const out = new Float32Array(Math.max(0, buckets));
  if (!channels.length || buckets <= 0) return out;
  const n = channels[0].length;
  if (n === 0) return out;
  for (let b = 0; b < buckets; b++) {
    const start = Math.floor((b * n) / buckets);
    const end = Math.max(start + 1, Math.floor(((b + 1) * n) / buckets));
    let peak = 0;
    for (const ch of channels) {
      for (let i = start; i < end && i < n; i++) {
        const v = Math.abs(ch[i]);
        if (v > peak) peak = v;
      }
    }
    out[b] = peak;
  }
  return out;
}

/** Scale so the loudest bucket fills the height; a silent track stays flat. */
export function normalisePeaks(peaks: Float32Array): Float32Array {
  let max = 0;
  for (const v of peaks) if (v > max) max = v;
  if (max === 0) return peaks;
  return peaks.map((v) => v / max);
}
