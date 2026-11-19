/** Format seconds as m:ss, flooring so the display never runs ahead of the audio. */
export function formatTime(seconds: number): string {
  const s = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

/** Spoken form for screen readers, e.g. "1 minute 5 seconds". */
export function spokenTime(seconds: number): string {
  const s = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  const m = Math.floor(s / 60);
  const r = s % 60;
  const parts: string[] = [];
  if (m > 0) parts.push(`${m} minute${m === 1 ? "" : "s"}`);
  parts.push(`${r} second${r === 1 ? "" : "s"}`);
  return parts.join(" ");
}
