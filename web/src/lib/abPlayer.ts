/**
 * Synchronised A/B playback of two decoded buffers.
 *
 * Both buffers always play together from the same context time and the same offset. Switching
 * between them only moves two gains, so the playback position cannot change on a switch: no source
 * is stopped, started or re-seeked. Graph per play session ("voice"):
 *
 *   source A -> voice fade A -> mix A --\
 *                                        +-> destination
 *   source B -> voice fade B -> mix B --/
 *
 * The mix gains carry the A/B crossfade and persist across seeks. The voice fades are short
 * envelopes on start and stop so play, pause and seek do not click either.
 */

import { RampedParam, type ParamLike } from "./ramp";

/** Length of the A/B crossfade. Short enough to feel instant, long enough not to click. */
export const CROSSFADE_S = 0.02;
/** Envelope on start, stop and seek. */
export const VOICE_FADE_S = 0.005;

export type Version = "original" | "stage";

export interface BufferLike {
  readonly duration: number;
  readonly length: number;
  readonly sampleRate: number;
  readonly numberOfChannels: number;
  getChannelData(channel: number): Float32Array;
}

export interface GainLike {
  readonly gain: ParamLike;
  connect(destination: never): unknown;
  disconnect(): void;
}

export interface SourceLike {
  buffer: BufferLike | null;
  connect(destination: never): unknown;
  disconnect(): void;
  start(when: number, offset: number): void;
  stop(when: number): void;
  onended: ((this: never, ev: never) => unknown) | null;
}

/** The subset of BaseAudioContext used here; a real AudioContext satisfies it. */
export interface ContextLike {
  readonly currentTime: number;
  readonly destination: unknown;
  createGain(): GainLike;
  createBufferSource(): SourceLike;
}

/** Linear (constant-sum) gains for the two versions while a crossfade is `x` of the way to B. */
export function crossfadeGains(x: number): { original: number; stage: number } {
  const c = Math.min(1, Math.max(0, x));
  return { original: 1 - c, stage: c };
}

interface Voice {
  sources: [SourceLike, SourceLike];
  fades: [GainLike, GainLike];
  fadeParams: [RampedParam, RampedParam];
}

export class ABPlayer {
  readonly duration: number;
  /** Absolute difference in length between the two files, in seconds. */
  readonly lengthMismatch: number;

  private readonly mix: [GainLike, GainLike];
  private readonly mixParams: [RampedParam, RampedParam];
  private voice: Voice | null = null;
  private active: Version = "original";
  private playing = false;
  /** Offset into the buffers at `startedAt` (when playing) or the paused position. */
  private offset = 0;
  private startedAt = 0;

  constructor(
    private readonly ctx: ContextLike,
    private readonly original: BufferLike,
    private readonly stage: BufferLike,
  ) {
    this.duration = Math.min(original.duration, stage.duration);
    this.lengthMismatch = Math.abs(original.duration - stage.duration);
    const now = ctx.currentTime;
    const gains = crossfadeGains(0);
    const mixA = ctx.createGain();
    const mixB = ctx.createGain();
    mixA.connect(ctx.destination as never);
    mixB.connect(ctx.destination as never);
    this.mix = [mixA, mixB];
    this.mixParams = [
      new RampedParam(mixA.gain, gains.original, now),
      new RampedParam(mixB.gain, gains.stage, now),
    ];
  }

  get isPlaying(): boolean {
    return this.playing;
  }

  get version(): Version {
    return this.active;
  }

  /** Current playback position in seconds, clamped to the shorter file. */
  get position(): number {
    const raw = this.playing ? this.offset + (this.ctx.currentTime - this.startedAt) : this.offset;
    return Math.min(this.duration, Math.max(0, raw));
  }

  /** Mix gains at context time t (defaults to now), from the scheduled automation. */
  gainsAt(t: number = this.ctx.currentTime): { original: number; stage: number } {
    return { original: this.mixParams[0].valueAt(t), stage: this.mixParams[1].valueAt(t) };
  }

  play(): void {
    if (this.playing) return;
    if (this.offset >= this.duration) this.offset = 0;
    this.startVoice(this.offset);
  }

  pause(): void {
    if (!this.playing) return;
    this.offset = this.position;
    this.playing = false;
    this.stopVoice();
  }

  toggle(): void {
    if (this.playing) this.pause();
    else this.play();
  }

  /** Seek to `seconds`. Both sources restart together at the same offset. */
  seek(seconds: number): void {
    const target = Math.min(this.duration, Math.max(0, seconds));
    if (this.playing) {
      this.stopVoice();
      this.startVoice(target);
    } else {
      this.offset = target;
    }
  }

  /** Switch to `version` with a crossfade. Never touches the sources or the position. */
  setVersion(version: Version): void {
    if (version === this.active) return;
    this.active = version;
    const now = this.ctx.currentTime;
    const gains = crossfadeGains(version === "stage" ? 1 : 0);
    this.mixParams[0].rampTo(gains.original, now, CROSSFADE_S);
    this.mixParams[1].rampTo(gains.stage, now, CROSSFADE_S);
  }

  switchVersion(): void {
    this.setVersion(this.active === "original" ? "stage" : "original");
  }

  /**
   * Call regularly (for example once per animation frame). Returns true when playback reached the
   * end, in which case the player has stopped and rewound to the start.
   */
  tick(): boolean {
    if (this.playing && this.position >= this.duration) {
      this.playing = false;
      this.offset = 0;
      this.stopVoice();
      return true;
    }
    return false;
  }

  dispose(): void {
    if (this.playing) this.pause();
    for (const m of this.mix) m.disconnect();
  }

  private startVoice(offset: number): void {
    const now = this.ctx.currentTime;
    const buffers: [BufferLike, BufferLike] = [this.original, this.stage];
    const sources = buffers.map((buffer, i) => {
      const src = this.ctx.createBufferSource();
      src.buffer = buffer;
      const fade = this.ctx.createGain();
      src.connect(fade as never);
      fade.connect(this.mix[i] as never);
      return { src, fade };
    });
    const [a, b] = sources as [(typeof sources)[0], (typeof sources)[0]];
    const fadeParams: [RampedParam, RampedParam] = [
      new RampedParam(a.fade.gain, 0, now),
      new RampedParam(b.fade.gain, 0, now),
    ];
    for (const p of fadeParams) p.rampTo(1, now, VOICE_FADE_S);
    // Same `when` and same `offset` for both: this is the whole synchronisation contract.
    a.src.start(now, offset);
    b.src.start(now, offset);
    this.voice = { sources: [a.src, b.src], fades: [a.fade, b.fade], fadeParams };
    this.offset = offset;
    this.startedAt = now;
    this.playing = true;
  }

  private stopVoice(): void {
    const voice = this.voice;
    if (!voice) return;
    this.voice = null;
    const now = this.ctx.currentTime;
    for (const p of voice.fadeParams) p.rampTo(0, now, VOICE_FADE_S);
    for (const s of voice.sources) s.stop(now + VOICE_FADE_S);
    // Disconnecting immediately would cut the fade-out short; the nodes are collected once the
    // stopped sources end, and the fades are disconnected with them.
    voice.sources[0].onended = () => {
      for (const s of voice.sources) s.disconnect();
      for (const f of voice.fades) f.disconnect();
    };
  }
}
