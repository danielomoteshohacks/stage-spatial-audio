import { describe, expect, it } from "vitest";
import { easedPath, opennessAt, placeObjects, toScreen, type Plan3 } from "./scene3";

const plan: Plan3 = {
  version: 3,
  tempo_bpm: 120,
  motion_depth: 1,
  sections: [
    { start_s: 0, end_s: 10, label: "verse", openness: 0.2 },
    { start_s: 10, end_s: 20, label: "chorus", openness: 1 },
  ],
  stems: [
    { name: "lead", leaf: "lead", kind: "object", role: "lead_vocal", mode: "mono", az: 0, el: 7, dist: 1, protected: true,
      feeds: [{ ch: "M", az: 0, el: 7 }] },
    { name: "pad", leaf: "pad", kind: "object", role: "pad", mode: "pair", az: 125, el: 30, dist: 2.6, breathes: true,
      feeds: [{ ch: "L", az: 125, el: 30 }, { ch: "R", az: -125, el: 30 }],
      events: [{ type: "lift", t0: 5, t1: 8, az: [[5, 0], [11, 0]], el: [[5, 0], [8, 18], [11, 0]] }] },
  ],
};

describe("scene3", () => {
  it("eases a keyframe path and is zero outside it", () => {
    const k: [number, number][] = [[0, 0], [1, 60], [2, -60], [3, 0]];
    expect(easedPath(k, -1)).toBe(0);
    expect(easedPath(k, 1)).toBeCloseTo(60);
    expect(easedPath(k, 1.5)).toBeCloseTo(0);
    expect(easedPath(k, 9)).toBe(0);
  });

  it("is quiet in a verse and open in a chorus", () => {
    expect(opennessAt(plan, 3)).toBeCloseTo(0.2);
    expect(opennessAt(plan, 16)).toBeCloseTo(1);
  });

  it("never moves a protected object and breathes the pads", () => {
    const verse = placeObjects(plan, 3);
    const chorus = placeObjects(plan, 16);
    expect(verse[0].az).toBe(0);
    expect(chorus[0].az).toBe(0);
    const padVerse = verse[1].feeds[0].az;
    const padChorus = chorus[1].feeds[0].az;
    expect(padChorus).toBeGreaterThan(padVerse);
    expect(padChorus).toBeCloseTo(125);
  });

  it("lifts the pads during a riser and mirrors a pair's feeds", () => {
    const up = placeObjects(plan, 8)[1];
    const before = placeObjects(plan, 4)[1];
    expect(up.feeds[0].el).toBeGreaterThan(before.feeds[0].el + 10);
    expect(up.feeds[0].az).toBeCloseTo(-up.feeds[1].az);
  });

  it("puts straight ahead at the top of the screen and the left on the left", () => {
    const [x0, y0] = toScreen(0, 2, 100);
    expect(x0).toBeCloseTo(0);
    expect(y0).toBeLessThan(0);
    expect(toScreen(90, 2, 100)[0]).toBeLessThan(0);
  });
});
