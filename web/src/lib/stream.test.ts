import { describe, expect, it } from "vitest";
import { contiguousUntil, planSchedule, segmentStarts, trimFrames } from "./stream";

describe("segment scheduling", () => {
  const d = [8, 18.5, 18.5, 4];

  it("lays segments end to end from their own durations", () => {
    expect(segmentStarts(d)).toEqual([0, 8, 26.5, 45]);
  });

  it("knows how far playback can go without a gap", () => {
    expect(contiguousUntil([8, 18.5, undefined, 4])).toBe(26.5);
    expect(contiguousUntil([undefined, 8])).toBe(0);
    expect(contiguousUntil(d)).toBe(49);
  });

  it("plans a start from zero as every segment back to back", () => {
    const p = planSchedule(d, 0);
    expect(p.map((x) => [x.index, x.delay, x.offset])).toEqual([
      [0, 0, 0],
      [1, 8, 0],
      [2, 26.5, 0],
      [3, 45, 0],
    ]);
  });

  it("plans a start in the middle of a segment, dropping the ones already played", () => {
    const p = planSchedule(d, 30);
    expect(p.map((x) => [x.index, x.delay, x.offset])).toEqual([
      [2, 0, 3.5],
      [3, 15, 0],
    ]);
  });

  it("stops at the first segment that does not exist yet", () => {
    const p = planSchedule([8, 18.5, undefined, 4], 0);
    expect(p.map((x) => x.index)).toEqual([0, 1]);
  });

  it("scales the codec context to the decoder's rate", () => {
    const meta = { pre: 2400, post: 0, sample_rate: 48000 };
    expect(trimFrames(meta, 48000)).toEqual([2400, 0]);
    expect(trimFrames(meta, 44100)).toEqual([2205, 0]);
  });
});
