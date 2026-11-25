import { describe, expect, it } from "vitest";
import { balancedOrders, commonLoopSeconds, matchGains, rmsOf, shuffle, toCsv, type Trial } from "./blindtest";

describe("blind test", () => {
  it("rotates a shuffled order so every condition lands on every letter once", () => {
    const orders = balancedOrders(["original", "v3", "reference"]);
    expect(orders).toHaveLength(3);
    for (let letter = 0; letter < 3; letter++) {
      expect(new Set(orders.map((o) => o[letter])).size).toBe(3);
    }
  });

  it("keeps every item when shuffling", () => {
    expect(shuffle([1, 2, 3, 4, 5]).sort()).toEqual([1, 2, 3, 4, 5]);
  });

  it("loops all letters over the shortest buffer so they stay time-locked", () => {
    expect(commonLoopSeconds([{ duration: 31 }, { duration: 29.5 }, { duration: 30 }])).toBe(29.5);
    expect(commonLoopSeconds([])).toBe(0);
  });

  it("matches loudness by turning the louder ones down, never the quiet one up", () => {
    const g = matchGains({ a: 0.2, b: 0.1, c: 0.4 });
    expect(g.b).toBe(1);
    expect(g.a).toBeCloseTo(0.5);
    expect(g.c).toBeCloseTo(0.25);
    expect(Math.max(...Object.values(g))).toBe(1);
  });

  it("measures RMS over the middle of the signal only", () => {
    const x = new Float32Array(100).fill(0.5);
    x.fill(1, 0, 10);
    expect(rmsOf([x])).toBeCloseTo(0.5);
  });

  it("writes one CSV row per trial with the reference file and escapes commas", () => {
    const t: Trial = {
      trial: 1, at: "2026-11-25T10:00:00Z", track: "Song, the", order: ["v3", "reference", "original"],
      ranking: ["v3", "reference", "original"], outside: "v3", natural: "original",
      gains_db: { v3: -1.5, original: 0 }, reference_file: "ref.m4a",
    };
    const lines = toCsv([t]).trim().split("\n");
    expect(lines).toHaveLength(2);
    expect(lines[0]).toContain("order_D");
    expect(lines[0]).toContain("reference_file");
    expect(lines[1]).toContain('"Song, the"');
    expect(lines[1]).toContain("ref.m4a");
    expect(lines[1]).toContain("v3:-1.50");
  });
});
