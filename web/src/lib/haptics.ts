// The "Feel" layer: short vibrations on the kick and sub-bass, on phones that can vibrate
// (Android Chrome; iOS Safari has no Vibration API, so the control is hidden there).
//
// Onsets come from the low band of the original (below 150 Hz, where the kick and the 808
// live): a rectified, smoothed envelope at 200 frames per second, with peaks that rise 6 dB over
// the previous 50 ms and are at least 120 ms apart. During playback each onset that the
// playhead crosses fires one pulse whose length (8 to 40 ms) follows its strength and the
// listener's intensity control.

export interface Onset {
  t: number;
  strength: number; // 0 to 1
}

export const canVibrate = (): boolean => typeof navigator !== "undefined" && "vibrate" in navigator;

/** Onsets of the low band of a mono signal. Exported for tests. */
export function lowOnsets(x: Float32Array, sampleRate: number): Onset[] {
  // Two one-pole low-passes at about 150 Hz, then the envelope.
  const a = Math.exp((-2 * Math.PI * 150) / sampleRate);
  const hop = Math.max(1, Math.round(sampleRate / 200));
  const frames: number[] = [];
  let y1 = 0;
  let y2 = 0;
  let acc = 0;
  for (let i = 0; i < x.length; i++) {
    y1 = (1 - a) * x[i] + a * y1;
    y2 = (1 - a) * y1 + a * y2;
    acc += Math.abs(y2);
    if ((i + 1) % hop === 0) {
      frames.push(acc / hop);
      acc = 0;
    }
  }
  const peak = Math.max(1e-9, ...frames);
  const out: Onset[] = [];
  let last = -1;
  for (let k = 10; k < frames.length - 1; k++) {
    const before = frames.slice(k - 10, k).reduce((s, v) => s + v, 0) / 10;
    const rising = frames[k] > 2 * before && frames[k] >= frames[k + 1] && frames[k] > 0.15 * peak;
    const t = (k * hop) / sampleRate;
    if (rising && (last < 0 || t - last >= 0.12)) {
      out.push({ t, strength: Math.min(1, frames[k] / peak) });
      last = t;
    }
  }
  return out;
}

export class HapticFeel {
  private onsets: Onset[];
  private next = 0;
  intensity = 0.6;
  enabled = false;

  constructor(onsets: Onset[]) {
    this.onsets = onsets;
  }

  /** Call on seek or loop: start from the first onset after `t`. */
  reset(t: number): void {
    this.next = this.onsets.findIndex((o) => o.t >= t);
    if (this.next < 0) this.next = this.onsets.length;
  }

  /** Call every animation frame with the playhead; fires the onsets it has passed. */
  tick(t: number): void {
    if (!this.enabled || !canVibrate()) return;
    let fired = 0;
    while (this.next < this.onsets.length && this.onsets[this.next].t <= t) {
      const o = this.onsets[this.next++];
      if (t - o.t < 0.08) fired = Math.max(fired, o.strength);
    }
    if (fired > 0) navigator.vibrate(Math.round(8 + 32 * fired * this.intensity));
  }
}
