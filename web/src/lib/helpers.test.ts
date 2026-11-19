import { describe, expect, it } from "vitest";
import { FakeBuffer } from "./fakeAudio";
import { pairFiles } from "./pairing";
import { computePeaks } from "./peaks";
import { formatTime, spokenTime } from "./time";

describe("pairFiles", () => {
  it("recognises the render_clip.py names in either order", () => {
    const o = { name: "input_stereo.wav" };
    const st = { name: "input_stage.wav" };
    expect(pairFiles([o, st])).toEqual({ ok: true, original: o, stage: st, guessed: false });
    expect(pairFiles([st, o])).toEqual({ ok: true, original: o, stage: st, guessed: false });
  });

  it("keeps drop order and flags a guess when names do not decide", () => {
    const a = { name: "a.wav" };
    const b = { name: "b.wav" };
    expect(pairFiles([a, b])).toEqual({ ok: true, original: a, stage: b, guessed: true });
  });

  it("ignores 'stage' in the extension only", () => {
    const a = { name: "song.stage" };
    const b = { name: "song_stage.wav" };
    const r = pairFiles([a, b]);
    expect(r.ok && r.stage).toBe(b);
  });

  it("rejects anything but two files", () => {
    expect(pairFiles([]).ok).toBe(false);
    expect(pairFiles([{ name: "x" }]).ok).toBe(false);
    expect(pairFiles([{ name: "x" }, { name: "y" }, { name: "z" }]).ok).toBe(false);
  });
});

describe("computePeaks", () => {
  it("takes min and max across channels per bucket", () => {
    const l = Float32Array.from([0, 0.5, -0.25, 0, 0, 0, 0.1, -0.1]);
    const r = Float32Array.from([0, -0.75, 0, 0, 0.2, 0, 0, 0]);
    const p = computePeaks(new FakeBuffer(8, [l, r]), 4);
    expect(Array.from(p.max)).toEqual([0.5, 0, Math.fround(0.2), Math.fround(0.1)]);
    expect(Array.from(p.min)).toEqual([-0.75, -0.25, 0, Math.fround(-0.1)]);
  });

  it("handles more buckets than samples and empty buffers", () => {
    const p = computePeaks(new FakeBuffer(4, [Float32Array.from([0.5, -0.5])]), 5);
    expect(p.max.length).toBe(5);
    expect(Math.max(...p.max)).toBe(0.5);
    const e = computePeaks(new FakeBuffer(4, [new Float32Array(0)]), 3);
    expect(Array.from(e.max)).toEqual([0, 0, 0]);
  });
});

describe("time formatting", () => {
  it("formats m:ss and floors", () => {
    expect(formatTime(0)).toBe("0:00");
    expect(formatTime(7.99)).toBe("0:07");
    expect(formatTime(65)).toBe("1:05");
    expect(formatTime(Number.NaN)).toBe("0:00");
  });

  it("has a spoken form", () => {
    expect(spokenTime(1)).toBe("1 second");
    expect(spokenTime(65)).toBe("1 minute 5 seconds");
  });
});
