// Sample-locked A/B player. Every buffer (original, full spatial render, spatial stems) plays from
// its own source node, all started at the same AudioContext time from the same offset, so they
// stay in sync to the sample. Switching between original and spatial only moves two gains, with
// a 30 ms ramp, so the switch is seamless and playback never restarts.
//
// Graph:
//   original ----------------------------------------------> originalGain --\
//   spatial.flac ---------------> fullGain ---\                               >-- destination
//   stem_k -----> stemGain_k ---> stemsBus ---->- spatialGain --------------/

export const CROSSFADE_S = 0.03;
/** Lead time before a synchronised start, so every node is scheduled for the same instant. */
const START_LEAD_S = 0.04;

export type Side = "original" | "spatial";

export interface LoopRegion {
  start: number;
  end: number;
}

export interface StemMix {
  solo: string[];
  muted: string[];
}

/** Gain of each stem under solo and mute: any solo silences the rest; mute always wins. */
export function stemGains(names: string[], mix: StemMix): Record<string, number> {
  const anySolo = mix.solo.length > 0;
  const out: Record<string, number> = {};
  for (const n of names) {
    const audible = (!anySolo || mix.solo.includes(n)) && !mix.muted.includes(n);
    out[n] = audible ? 1 : 0;
  }
  return out;
}

/** Where a source started at `offset` is after `elapsed` seconds, given an optional loop. */
export function positionAt(
  offset: number,
  elapsed: number,
  duration: number,
  loop: LoopRegion | null,
): number {
  const raw = offset + elapsed;
  if (loop && loop.end > loop.start && raw >= loop.end) {
    const len = loop.end - loop.start;
    return loop.start + ((raw - loop.end) % len);
  }
  return Math.min(raw, duration);
}

/** A loop of at least 0.25 s inside the track, or null. */
export function clampLoop(a: number, b: number, duration: number): LoopRegion | null {
  const start = Math.max(0, Math.min(a, b));
  const end = Math.min(duration, Math.max(a, b));
  return end - start >= 0.25 ? { start, end } : null;
}

export class SyncPlayer {
  readonly ctx: AudioContext;
  private originalBuf: AudioBuffer;
  private spatialBuf: AudioBuffer;
  private stemBufs: Record<string, AudioBuffer>;
  private originalGain: GainNode;
  private spatialGain: GainNode;
  private fullGain: GainNode;
  private stemsBus: GainNode;
  private stemGainNodes: Record<string, GainNode> = {};
  private sources: AudioBufferSourceNode[] = [];
  private startedAt = 0;
  private offset = 0;
  private playing = false;
  private side: Side = "spatial";
  private loop: LoopRegion | null = null;
  private usingStems = false;
  private mix: StemMix = { solo: [], muted: [] };
  onended: (() => void) | null = null;

  constructor(
    ctx: AudioContext,
    buffers: { original: AudioBuffer; spatial: AudioBuffer; stems: Record<string, AudioBuffer> },
  ) {
    this.ctx = ctx;
    this.originalBuf = buffers.original;
    this.spatialBuf = buffers.spatial;
    this.stemBufs = buffers.stems;
    this.originalGain = new GainNode(ctx, { gain: 0 });
    this.spatialGain = new GainNode(ctx, { gain: 1 });
    this.fullGain = new GainNode(ctx, { gain: 1 });
    this.stemsBus = new GainNode(ctx, { gain: 0 });
    this.originalGain.connect(ctx.destination);
    this.spatialGain.connect(ctx.destination);
    this.fullGain.connect(this.spatialGain);
    this.stemsBus.connect(this.spatialGain);
    for (const name of Object.keys(this.stemBufs)) {
      const g = new GainNode(ctx, { gain: 1 });
      g.connect(this.stemsBus);
      this.stemGainNodes[name] = g;
    }
  }

  get duration(): number {
    return this.originalBuf.duration;
  }

  get isPlaying(): boolean {
    return this.playing;
  }

  get activeSide(): Side {
    return this.side;
  }

  get stemNames(): string[] {
    return Object.keys(this.stemBufs);
  }

  get isStemMix(): boolean {
    return this.usingStems;
  }

  get stemMix(): StemMix {
    return { solo: [...this.mix.solo], muted: [...this.mix.muted] };
  }

  get loopRegion(): LoopRegion | null {
    return this.loop;
  }

  get currentTime(): number {
    if (!this.playing) return this.offset;
    const elapsed = Math.max(0, this.ctx.currentTime - this.startedAt);
    return positionAt(this.offset, elapsed, this.duration, this.loop);
  }

  private ramp(param: AudioParam, target: number): void {
    const now = this.ctx.currentTime;
    param.cancelScheduledValues(now);
    param.setValueAtTime(param.value, now);
    param.linearRampToValueAtTime(target, now + CROSSFADE_S);
  }

  private makeSource(buffer: AudioBuffer, dest: AudioNode): AudioBufferSourceNode {
    const src = new AudioBufferSourceNode(this.ctx, { buffer });
    if (this.loop) {
      src.loop = true;
      src.loopStart = this.loop.start;
      src.loopEnd = this.loop.end;
    }
    src.connect(dest);
    return src;
  }

  private stopSources(): void {
    for (const s of this.sources) {
      s.onended = null;
      try {
        s.stop();
      } catch {
        // A source that already ended cannot be stopped again; nothing to do.
      }
      s.disconnect();
    }
    this.sources = [];
  }

  async play(): Promise<void> {
    if (this.ctx.state !== "running") await this.ctx.resume();
    if (this.playing) return;
    let at = this.offset >= this.duration - 0.01 ? 0 : this.offset;
    if (this.loop && (at < this.loop.start || at >= this.loop.end)) at = this.loop.start;
    const srcs = [this.makeSource(this.originalBuf, this.originalGain), this.makeSource(this.spatialBuf, this.fullGain)];
    for (const [name, buf] of Object.entries(this.stemBufs)) {
      srcs.push(this.makeSource(buf, this.stemGainNodes[name]));
    }
    const when = this.ctx.currentTime + START_LEAD_S;
    for (const s of srcs) s.start(when, at);
    // All sources have the same length, so the first one's end is the end of playback.
    srcs[0].onended = () => {
      if (!this.playing) return;
      this.playing = false;
      this.offset = 0;
      this.stopSources();
      this.onended?.();
    };
    this.sources = srcs;
    this.startedAt = when;
    this.offset = at;
    this.playing = true;
  }

  pause(): void {
    if (!this.playing) return;
    this.offset = this.currentTime;
    this.playing = false;
    this.stopSources();
  }

  async seek(seconds: number): Promise<void> {
    const t = Math.max(0, Math.min(seconds, this.duration));
    const wasPlaying = this.playing;
    if (wasPlaying) {
      this.playing = false;
      this.stopSources();
    }
    this.offset = t;
    if (wasPlaying) await this.play();
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

  async setLoop(region: LoopRegion | null): Promise<void> {
    const t = this.currentTime;
    this.loop = region;
    // Loop points are fixed per source here so that the position maths stays exact; restarting
    // every node together keeps them in sync.
    if (this.playing) {
      this.playing = false;
      this.stopSources();
      this.offset = t;
      await this.play();
    } else if (region && (this.offset < region.start || this.offset >= region.end)) {
      this.offset = region.start;
    }
  }

  /** Mix the spatial side from the stems with solo and mute, instead of the full render. */
  setStemMix(mix: StemMix): void {
    if (!this.stemNames.length) return;
    this.mix = { solo: [...mix.solo], muted: [...mix.muted] };
    const gains = stemGains(this.stemNames, this.mix);
    for (const [name, g] of Object.entries(gains)) this.ramp(this.stemGainNodes[name].gain, g);
    if (!this.usingStems) {
      this.usingStems = true;
      this.ramp(this.stemsBus.gain, 1);
      this.ramp(this.fullGain.gain, 0);
    }
  }

  /** Back to spatial.flac, the full render, with every stem cleared. */
  useFullRender(): void {
    this.mix = { solo: [], muted: [] };
    for (const g of Object.values(this.stemGainNodes)) this.ramp(g.gain, 1);
    this.usingStems = false;
    this.ramp(this.stemsBus.gain, 0);
    this.ramp(this.fullGain.gain, 1);
  }

  dispose(): void {
    this.playing = false;
    this.stopSources();
    for (const n of [this.originalGain, this.spatialGain, this.fullGain, this.stemsBus, ...Object.values(this.stemGainNodes)]) {
      n.disconnect();
    }
  }
}
