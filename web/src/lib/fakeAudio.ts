/**
 * Minimal fake Web Audio objects for tests. They record every call so tests can check what was
 * scheduled, and FakeParam evaluates its own automation timeline the way the Web Audio spec does
 * for setValueAtTime and linearRampToValueAtTime, independently of RampedParam's model.
 */

import type { BufferLike, ContextLike, GainLike, SourceLike } from "./abPlayer";

type ParamEvent =
  | { kind: "set"; value: number; time: number }
  | { kind: "linear"; value: number; time: number };

export class FakeParam {
  events: ParamEvent[] = [];
  log: string[] = [];

  constructor(private readonly defaultValue = 1) {}

  setValueAtTime(value: number, time: number): void {
    this.log.push(`set ${value} @${time}`);
    this.insert({ kind: "set", value, time });
  }

  linearRampToValueAtTime(value: number, time: number): void {
    this.log.push(`linear ${value} @${time}`);
    this.insert({ kind: "linear", value, time });
  }

  cancelScheduledValues(time: number): void {
    this.log.push(`cancel @${time}`);
    this.events = this.events.filter((e) => e.time < time);
  }

  private insert(e: ParamEvent): void {
    // Events at the same time keep insertion order, as the spec requires.
    let i = this.events.length;
    while (i > 0 && (this.events[i - 1] as ParamEvent).time > e.time) i--;
    this.events.splice(i, 0, e);
  }

  /** Value at time t from the recorded events. */
  valueAt(t: number): number {
    let value = this.defaultValue;
    let prevTime = 0;
    for (const e of this.events) {
      if (e.time <= t) {
        value = e.value;
        prevTime = e.time;
        continue;
      }
      if (e.kind === "linear") {
        const x = (t - prevTime) / (e.time - prevTime);
        return value + (e.value - value) * x;
      }
      return value;
    }
    return value;
  }
}

export class FakeGain implements GainLike {
  readonly gain = new FakeParam(1);
  connections: unknown[] = [];
  disconnected = false;
  connect(destination: never): unknown {
    this.connections.push(destination);
    return destination;
  }
  disconnect(): void {
    this.disconnected = true;
  }
}

export class FakeSource implements SourceLike {
  buffer: BufferLike | null = null;
  onended: ((this: never, ev: never) => unknown) | null = null;
  connections: unknown[] = [];
  starts: { when: number; offset: number }[] = [];
  stops: number[] = [];
  disconnected = false;
  connect(destination: never): unknown {
    this.connections.push(destination);
    return destination;
  }
  disconnect(): void {
    this.disconnected = true;
  }
  start(when: number, offset: number): void {
    this.starts.push({ when, offset });
  }
  stop(when: number): void {
    this.stops.push(when);
  }
}

export class FakeContext implements ContextLike {
  currentTime = 0;
  readonly destination = { name: "destination" };
  gains: FakeGain[] = [];
  sources: FakeSource[] = [];

  createGain(): FakeGain {
    const g = new FakeGain();
    this.gains.push(g);
    return g;
  }

  createBufferSource(): FakeSource {
    const s = new FakeSource();
    this.sources.push(s);
    return s;
  }
}

export class FakeBuffer implements BufferLike {
  readonly numberOfChannels: number;
  readonly length: number;
  private readonly data: Float32Array[];

  constructor(
    readonly sampleRate: number,
    channels: Float32Array[],
  ) {
    this.data = channels;
    this.numberOfChannels = channels.length;
    this.length = channels[0]?.length ?? 0;
  }

  get duration(): number {
    return this.length / this.sampleRate;
  }

  getChannelData(channel: number): Float32Array {
    const d = this.data[channel];
    if (!d) throw new RangeError(`no channel ${channel}`);
    return d;
  }

  /** A silent stereo buffer of `seconds` at `sampleRate`. */
  static silent(seconds: number, sampleRate = 48000): FakeBuffer {
    const n = Math.round(seconds * sampleRate);
    return new FakeBuffer(sampleRate, [new Float32Array(n), new Float32Array(n)]);
  }
}
