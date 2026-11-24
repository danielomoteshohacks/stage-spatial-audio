export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  return `${m}:${Math.floor(s).toString().padStart(2, "0")}`;
}

export function formatPrecise(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00.0";
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDuration(seconds: number): string {
  return seconds < 1 ? `${Math.round(seconds * 1000)} ms` : `${seconds.toFixed(2)} s`;
}

export const ALLOWED = [".wav", ".flac", ".mp3", ".ogg", ".m4a"];

/** Level envelope (0 to 1) of an audio buffer at `rate` frames per second, for the stage view. */
export function levelEnvelope(buffer: AudioBuffer, rate = 50): Float32Array {
  const hop = Math.max(1, Math.round(buffer.sampleRate / rate));
  const n = Math.ceil(buffer.length / hop);
  const out = new Float32Array(n);
  const chans = Array.from({ length: buffer.numberOfChannels }, (_, i) => buffer.getChannelData(i));
  let peak = 1e-9;
  for (let k = 0; k < n; k++) {
    let s = 0;
    const a = k * hop;
    const b = Math.min(buffer.length, a + hop);
    for (const c of chans) for (let i = a; i < b; i++) s += c[i] * c[i];
    out[k] = Math.sqrt(s / Math.max(1, (b - a) * chans.length));
    peak = Math.max(peak, out[k]);
  }
  for (let k = 0; k < n; k++) out[k] /= peak;
  return out;
}
