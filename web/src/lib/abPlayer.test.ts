import { beforeEach, describe, expect, it } from "vitest";
import { ABPlayer, CROSSFADE_S, VOICE_FADE_S, crossfadeGains } from "./abPlayer";
import { FakeBuffer, FakeContext, type FakeGain, type FakeSource } from "./fakeAudio";

function setup(originalS = 10, stageS = 10) {
  const ctx = new FakeContext();
  const original = FakeBuffer.silent(originalS);
  const stage = FakeBuffer.silent(stageS);
  const player = new ABPlayer(ctx, original, stage);
  const [mixA, mixB] = ctx.gains as [FakeGain, FakeGain];
  return { ctx, original, stage, player, mixA, mixB };
}

/** Sample the fake params' own timelines (not the player's model) across [t0, t1]. */
function sample(a: FakeGain, b: FakeGain, t0: number, t1: number, steps = 2000) {
  const out: { t: number; a: number; b: number }[] = [];
  for (let i = 0; i <= steps; i++) {
    const t = t0 + ((t1 - t0) * i) / steps;
    out.push({ t, a: a.gain.valueAt(t), b: b.gain.valueAt(t) });
  }
  return out;
}

function maxStep(values: number[]): number {
  let m = 0;
  for (let i = 1; i < values.length; i++) {
    m = Math.max(m, Math.abs((values[i] as number) - (values[i - 1] as number)));
  }
  return m;
}

describe("crossfadeGains", () => {
  it("is constant-sum and clamped", () => {
    for (const x of [-1, 0, 0.25, 0.5, 0.75, 1, 2]) {
      const g = crossfadeGains(x);
      expect(g.original + g.stage).toBeCloseTo(1, 12);
      expect(g.original).toBeGreaterThanOrEqual(0);
      expect(g.stage).toBeGreaterThanOrEqual(0);
    }
    expect(crossfadeGains(0)).toEqual({ original: 1, stage: 0 });
    expect(crossfadeGains(1)).toEqual({ original: 0, stage: 1 });
  });
});

describe("ABPlayer sync", () => {
  let s: ReturnType<typeof setup>;
  beforeEach(() => {
    s = setup();
  });

  it("starts both sources at the same context time and offset", () => {
    s.ctx.currentTime = 3.25;
    s.player.seek(4);
    s.player.play();
    const [a, b] = s.ctx.sources as [FakeSource, FakeSource];
    expect(s.ctx.sources).toHaveLength(2);
    expect(a.buffer).toBe(s.original);
    expect(b.buffer).toBe(s.stage);
    expect(a.starts).toEqual([{ when: 3.25, offset: 4 }]);
    expect(b.starts).toEqual(a.starts);
  });

  it("routes each source through its own mix gain", () => {
    s.player.play();
    const [a, b] = s.ctx.sources as [FakeSource, FakeSource];
    const fadeA = a.connections[0] as FakeGain;
    const fadeB = b.connections[0] as FakeGain;
    expect(fadeA.connections).toEqual([s.mixA]);
    expect(fadeB.connections).toEqual([s.mixB]);
    expect(s.mixA.connections).toEqual([s.ctx.destination]);
    expect(s.mixB.connections).toEqual([s.ctx.destination]);
  });

  it("starts on the original only", () => {
    expect(s.player.version).toBe("original");
    expect(s.player.gainsAt(0)).toEqual({ original: 1, stage: 0 });
    expect(s.mixA.gain.valueAt(0)).toBe(1);
    expect(s.mixB.gain.valueAt(0)).toBe(0);
  });

  it("A/B switching never stops, starts or re-seeks a source", () => {
    s.player.play();
    s.ctx.currentTime = 2.5;
    const before = s.player.position;
    for (let i = 0; i < 7; i++) {
      s.player.switchVersion();
      expect(s.player.position).toBe(before);
    }
    expect(s.ctx.sources).toHaveLength(2);
    for (const src of s.ctx.sources) {
      expect(src.starts).toHaveLength(1);
      expect(src.stops).toHaveLength(0);
    }
  });

  it("position keeps advancing with the clock across switches", () => {
    s.ctx.currentTime = 1;
    s.player.play();
    s.ctx.currentTime = 2;
    s.player.setVersion("stage");
    s.ctx.currentTime = 3.5;
    s.player.setVersion("original");
    expect(s.player.position).toBeCloseTo(2.5, 12);
  });

  it("switching while paused keeps the paused position and starts nothing", () => {
    s.player.seek(6.5);
    s.player.setVersion("stage");
    expect(s.player.position).toBe(6.5);
    expect(s.ctx.sources).toHaveLength(0);
    s.player.play();
    const [a, b] = s.ctx.sources as [FakeSource, FakeSource];
    expect(a.starts[0]?.offset).toBe(6.5);
    expect(b.starts[0]?.offset).toBe(6.5);
  });

  it("the chosen version survives a seek", () => {
    s.player.play();
    s.player.setVersion("stage");
    s.ctx.currentTime = 1;
    s.player.seek(5);
    expect(s.player.version).toBe("stage");
    expect(s.player.gainsAt(1.5)).toEqual({ original: 0, stage: 1 });
  });

  it("seek while playing restarts both sources together at the new offset", () => {
    s.player.play();
    s.ctx.currentTime = 2;
    s.player.seek(7);
    const [oldA, oldB, newA, newB] = s.ctx.sources as FakeSource[] as [
      FakeSource,
      FakeSource,
      FakeSource,
      FakeSource,
    ];
    expect(oldA.stops).toEqual([2 + VOICE_FADE_S]);
    expect(oldB.stops).toEqual([2 + VOICE_FADE_S]);
    expect(newA.starts).toEqual([{ when: 2, offset: 7 }]);
    expect(newB.starts).toEqual(newA.starts);
    expect(s.player.position).toBe(7);
    s.ctx.currentTime = 2.75;
    expect(s.player.position).toBeCloseTo(7.75, 12);
  });

  it("pause stores the position and play resumes both from it", () => {
    s.player.play();
    s.ctx.currentTime = 4.2;
    s.player.pause();
    expect(s.player.isPlaying).toBe(false);
    s.ctx.currentTime = 9;
    expect(s.player.position).toBeCloseTo(4.2, 12);
    s.player.play();
    const [, , a, b] = s.ctx.sources as [FakeSource, FakeSource, FakeSource, FakeSource];
    expect(a.starts).toEqual([{ when: 9, offset: s.player.position }]);
    expect(b.starts).toEqual(a.starts);
    expect(a.starts[0]?.offset).toBeCloseTo(4.2, 12);
  });

  it("clamps seeks to the shorter file and reports the mismatch", () => {
    const m = setup(10, 9.5);
    expect(m.player.duration).toBe(9.5);
    expect(m.player.lengthMismatch).toBeCloseTo(0.5, 9);
    m.player.seek(20);
    expect(m.player.position).toBe(9.5);
    m.player.seek(-3);
    expect(m.player.position).toBe(0);
  });

  it("stops and rewinds at the end", () => {
    s.player.play();
    s.ctx.currentTime = 5;
    expect(s.player.tick()).toBe(false);
    s.ctx.currentTime = 10.01;
    expect(s.player.tick()).toBe(true);
    expect(s.player.isPlaying).toBe(false);
    expect(s.player.position).toBe(0);
  });
});

describe("ABPlayer crossfade", () => {
  it("ramps over CROSSFADE_S, about 20 ms", () => {
    expect(CROSSFADE_S).toBeGreaterThanOrEqual(0.015);
    expect(CROSSFADE_S).toBeLessThanOrEqual(0.03);
    const s = setup();
    s.player.play();
    s.ctx.currentTime = 1;
    s.player.setVersion("stage");
    expect(s.mixA.gain.log.slice(-3)).toEqual(["cancel @1", "set 1 @1", `linear 0 @${1 + CROSSFADE_S}`]);
    expect(s.mixB.gain.log.slice(-3)).toEqual(["cancel @1", "set 0 @1", `linear 1 @${1 + CROSSFADE_S}`]);
  });

  it("keeps the gains constant-sum and continuous through the fade", () => {
    const s = setup();
    s.player.play();
    s.ctx.currentTime = 1;
    s.player.setVersion("stage");
    const pts = sample(s.mixA, s.mixB, 0.99, 1 + CROSSFADE_S + 0.01);
    for (const p of pts) expect(p.a + p.b).toBeCloseTo(1, 9);
    // 2000 steps over 40 ms: a linear 20 ms ramp moves 1/1000 per step. A hard switch would be 1.
    expect(maxStep(pts.map((p) => p.a))).toBeLessThan(0.002);
    expect(maxStep(pts.map((p) => p.b))).toBeLessThan(0.002);
    expect(s.mixA.gain.valueAt(1 + CROSSFADE_S / 2)).toBeCloseTo(0.5, 9);
    expect(s.mixB.gain.valueAt(1 + CROSSFADE_S)).toBe(1);
  });

  it("a reversal mid-fade starts from the current gain, without a step", () => {
    const s = setup();
    s.player.play();
    s.ctx.currentTime = 1;
    s.player.setVersion("stage");
    const mid = 1 + CROSSFADE_S * 0.3;
    // What was heard before the reversal is sampled before it: rescheduling cannot change the past.
    const before = sample(s.mixA, s.mixB, 0.99, mid, 600);
    s.ctx.currentTime = mid;
    s.player.setVersion("original");
    expect(s.player.gainsAt(mid).stage).toBeCloseTo(0.3, 9);
    const after = sample(s.mixA, s.mixB, mid, mid + CROSSFADE_S + 0.01, 1400);
    const pts = [...before, ...after];
    for (const p of pts) expect(p.a + p.b).toBeCloseTo(1, 9);
    expect(maxStep(pts.map((p) => p.a))).toBeLessThan(0.002);
    expect(maxStep(pts.map((p) => p.b))).toBeLessThan(0.002);
    expect(s.mixB.gain.valueAt(mid + CROSSFADE_S)).toBe(0);
  });

  it("the player's gain model matches the scheduled automation", () => {
    const s = setup();
    s.player.play();
    const times = [0.5, 0.505, 0.512, 0.6];
    const versions = ["stage", "original", "stage", "original"] as const;
    // Compare each stretch right after it is scheduled, up to the next change.
    times.forEach((t, i) => {
      s.ctx.currentTime = t;
      s.player.setVersion(versions[i] as (typeof versions)[number]);
      const end = times[i + 1] ?? t + 0.05;
      for (let u = t; u < end; u += 0.0005) {
        const g = s.player.gainsAt(u);
        expect(g.original).toBeCloseTo(s.mixA.gain.valueAt(u), 9);
        expect(g.stage).toBeCloseTo(s.mixB.gain.valueAt(u), 9);
      }
    });
  });

  it("setting the active version again schedules nothing", () => {
    const s = setup();
    const before = s.mixA.gain.log.length;
    s.player.setVersion("original");
    expect(s.mixA.gain.log.length).toBe(before);
  });

  it("start, pause and seek use short fades on the voice, not hard steps", () => {
    const s = setup();
    s.ctx.currentTime = 1;
    s.player.play();
    const [a] = s.ctx.sources as [FakeSource];
    const fade = a.connections[0] as FakeGain;
    expect(fade.gain.valueAt(1)).toBe(0);
    expect(fade.gain.valueAt(1 + VOICE_FADE_S / 2)).toBeCloseTo(0.5, 9);
    expect(fade.gain.valueAt(1 + VOICE_FADE_S)).toBe(1);
    s.ctx.currentTime = 2;
    s.player.pause();
    expect(fade.gain.valueAt(2)).toBe(1);
    expect(fade.gain.valueAt(2 + VOICE_FADE_S)).toBe(0);
    expect(a.stops).toEqual([2 + VOICE_FADE_S]);
  });
});
