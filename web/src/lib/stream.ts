// Gapless playback of a song that is still being rendered.
//
// The original is one decoded buffer. The spatial render arrives as segments (decision 0027):
// each is decoded, its codec context trimmed, and scheduled to start exactly where the previous
// one ends, so the seams are sample-exact in the audio clock whatever the segments' rounded
// start times say. The original and the spatial segments are started from the same context time
// and the same offset, so switching between them moves two gains over 30 ms and never restarts
// playback (the v2 player's A/B design, now over segments).
//
// If playback catches up with the render the player stops and says so ("buffering") and resumes
// when a second of the next segment exists; it never plays silence on the spatial side.

export const CROSSFADE_S = 0.03;
const START_LEAD_S = 0.04;
/** Seconds of audio that must be ready beyond the playhead before a stalled player resumes. */
export const RESUME_AHEAD_S = 1.0;

export type Side = "original" | "spatial";

export interface SegmentMeta {
  index: number;
  file: string;
  start_s: number;
  duration_s: number;
  pre: number;
  post: number;
  samples: number;
  sample_rate: number;
  fmt: string;
  bytes: number;
}

/** Start time of each segment when they are laid end to end. */
export function segmentStarts(durations: number[]): number[] {
  const out: number[] = [];
  let t = 0;
  for (const d of durations) {
    out.push(t);
    t += d;
  }
  return out;
}

/** How far playback can go without a gap: the end of the first run of segments present from 0. */
export function contiguousUntil(durations: (number | undefined)[]): number {
  let t = 0;
  for (const d of durations) {
    if (d === undefined) break;
    t += d;
  }
  return t;
}

export interface ScheduledPart {
  index: number;
  /** Seconds after the start of playback at which the segment begins (0 when it is mid-way). */
  delay: number;
  /** Where in the segment's own buffer to begin. */
  offset: number;
}

/** The segments to start for playback beginning at `position`, in order. */
export function planSchedule(durations: (number | undefined)[], position: number): ScheduledPart[] {
  const parts: ScheduledPart[] = [];
  let t = 0;
  for (let i = 0; i < durations.length; i++) {
    const d = durations[i];
    if (d === undefined) break;
    const end = t + d;
    if (end > position) {
      parts.push({ index: i, delay: Math.max(0, t - position), offset: Math.max(0, position - t) });
    }
    t = end;
  }
  return parts;
}

/** Context samples at `rate` to drop at the start and end of a decoded segment. */
export function trimFrames(meta: Pick<SegmentMeta, "pre" | "post" | "sample_rate">, rate: number): [number, number] {
  const k = rate / meta.sample_rate;
  return [Math.round(meta.pre * k), Math.round(meta.post * k)];
}

export function trimBuffer(ctx: BaseAudioContext, decoded: AudioBuffer, meta: SegmentMeta): AudioBuffer {
  const [pre, post] = trimFrames(meta, decoded.sampleRate);
  const len = Math.max(1, decoded.length - pre - post);
  if (pre === 0 && post === 0) return decoded;
  const out = ctx.createBuffer(decoded.numberOfChannels, len, decoded.sampleRate);
  for (let c = 0; c < decoded.numberOfChannels; c++) {
    out.copyToChannel(decoded.getChannelData(c).subarray(pre, pre + len), c);
  }
  return out;
}

export class StreamPlayer {
  readonly ctx: AudioContext;
  private original: AudioBuffer;
  private segs: (AudioBuffer | undefined)[] = [];
  private originalGain: GainNode;
  private spatialGain: GainNode;
  private sources: AudioBufferSourceNode[] = [];
  private segSources = new Map<number, AudioBufferSourceNode>();
  private startedAt = 0;
  private offset = 0;
  private playing = false;
  private wantPlaying = false;
  private side: Side = "spatial";
  private complete = false;
  private timer: ReturnType<typeof setInterval> | null = null;
  onended: (() => void) | null = null;
  onbuffering: ((buffering: boolean) => void) | null = null;
  private stalled = false;

  constructor(ctx: AudioContext, original: AudioBuffer) {
    this.ctx = ctx;
    this.original = original;
    this.originalGain = new GainNode(ctx, { gain: 0 });
    this.spatialGain = new GainNode(ctx, { gain: 1 });
    this.originalGain.connect(ctx.destination);
    this.spatialGain.connect(ctx.destination);
  }

  get duration(): number {
    return this.original.duration;
  }
  get isPlaying(): boolean {
    return this.wantPlaying;
  }
  get activeSide(): Side {
    return this.side;
  }
  get isBuffering(): boolean {
    return this.stalled;
  }
  /** Seconds of the song whose spatial render exists without a gap. */
  get readyUntil(): number {
    return this.complete ? this.duration : contiguousUntil(this.segs.map((b) => b?.duration));
  }
  get isComplete(): boolean {
    return this.complete;
  }

  get currentTime(): number {
    if (!this.playing) return this.offset;
    return Math.min(this.offset + Math.max(0, this.ctx.currentTime - this.startedAt), this.duration);
  }

  setComplete(): void {
    this.complete = true;
  }

  addSegment(index: number, buffer: AudioBuffer): void {
    this.segs[index] = buffer;
    if (this.playing) this.scheduleSegment(index);
    if (this.stalled && this.readyUntil >= this.offset + RESUME_AHEAD_S) void this.resumeFromStall();
  }

  private ramp(param: AudioParam, target: number): void {
    const now = this.ctx.currentTime;
    param.cancelScheduledValues(now);
    param.setValueAtTime(param.value, now);
    param.linearRampToValueAtTime(target, now + CROSSFADE_S);
  }

  private stopSources(): void {
    for (const s of this.sources) {
      s.onended = null;
      try {
        s.stop();
      } catch {
        // A source that already ended cannot be stopped again.
      }
      s.disconnect();
    }
    this.sources = [];
    this.segSources.clear();
  }

  private scheduleSegment(index: number): void {
    const buf = this.segs[index];
    if (!buf || this.segSources.has(index)) return;
    const durations = this.segs.map((b) => b?.duration);
    const part = planSchedule(durations, this.offset).find((p) => p.index === index);
    if (!part) return;
    const absStart = this.startedAt + part.delay;
    // A segment that arrives after its time has passed starts from where the clock now is.
    const late = Math.max(0, this.ctx.currentTime - absStart);
    const src = new AudioBufferSourceNode(this.ctx, { buffer: buf });
    src.connect(this.spatialGain);
    src.start(Math.max(absStart, this.ctx.currentTime), part.offset + late);
    this.sources.push(src);
    this.segSources.set(index, src);
  }

  private begin(at: number): void {
    const when = this.ctx.currentTime + START_LEAD_S;
    const orig = new AudioBufferSourceNode(this.ctx, { buffer: this.original });
    orig.connect(this.originalGain);
    orig.start(when, at);
    orig.onended = () => {
      if (!this.playing || this.currentTime < this.duration - 0.2) return;
      this.playing = false;
      this.wantPlaying = false;
      this.offset = 0;
      this.stopSources();
      this.clearTimer();
      this.onended?.();
    };
    this.sources = [orig];
    this.startedAt = when;
    this.offset = at;
    this.playing = true;
    for (let i = 0; i < this.segs.length; i++) this.scheduleSegment(i);
  }

  private clearTimer(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  private watch(): void {
    this.clearTimer();
    this.timer = setInterval(() => {
      if (!this.playing || this.complete) return;
      if (this.currentTime >= this.readyUntil - 0.08) this.stall();
    }, 120);
  }

  private stall(): void {
    this.offset = this.currentTime;
    this.playing = false;
    this.stopSources();
    this.stalled = true;
    this.onbuffering?.(true);
  }

  private async resumeFromStall(): Promise<void> {
    this.stalled = false;
    this.onbuffering?.(false);
    if (this.wantPlaying) {
      this.begin(this.offset);
    }
  }

  async play(): Promise<void> {
    if (this.ctx.state !== "running") await this.ctx.resume();
    if (this.wantPlaying) return;
    this.wantPlaying = true;
    const at = this.offset >= this.duration - 0.01 ? 0 : this.offset;
    this.offset = at;
    if (!this.complete && this.readyUntil < at + RESUME_AHEAD_S) {
      this.stalled = true;
      this.onbuffering?.(true);
      this.watch();
      return;
    }
    this.begin(at);
    this.watch();
  }

  pause(): void {
    if (!this.wantPlaying) return;
    this.offset = this.currentTime;
    this.wantPlaying = false;
    this.playing = false;
    this.stopSources();
    this.clearTimer();
    if (this.stalled) {
      this.stalled = false;
      this.onbuffering?.(false);
    }
  }

  async seek(seconds: number): Promise<void> {
    const t = Math.max(0, Math.min(seconds, this.duration));
    const was = this.wantPlaying;
    if (was) this.pause();
    this.offset = t;
    if (was) await this.play();
  }

  setSide(side: Side): void {
    this.side = side;
    this.ramp(this.originalGain.gain, side === "original" ? 1 : 0);
    this.ramp(this.spatialGain.gain, side === "spatial" ? 1 : 0);
  }

  toggle(): Side {
    this.setSide(this.side === "spatial" ? "original" : "spatial");
    return this.side;
  }

  dispose(): void {
    this.wantPlaying = false;
    this.playing = false;
    this.stopSources();
    this.clearTimer();
    this.originalGain.disconnect();
    this.spatialGain.disconnect();
  }
}
