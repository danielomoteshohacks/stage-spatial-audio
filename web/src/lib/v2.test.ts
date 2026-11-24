import { describe, expect, it } from "vitest";
import { parseFlac, parseId3, parseMp4Moov } from "./artwork";
import { matchGains, rmsOf, shuffle, toCsv } from "./blindtest";
import { lowOnsets } from "./haptics";
import { contrast, paletteFromPixels, readable } from "./palette";
import { fromFloor, motionOffset, objectAt, toXYZ, type Plan } from "./scene";

const JPEG = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, ...new Array(40).fill(7)]);
const enc = (s: string) => new TextEncoder().encode(s);
const be32 = (n: number) => [(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255];

function synchsafe(n: number): number[] {
  return [(n >> 21) & 127, (n >> 14) & 127, (n >> 7) & 127, n & 127];
}

describe("cover art parsers", () => {
  it("reads an ID3v2.3 APIC frame and the title", () => {
    const apicBody = [0, ...enc("image/jpeg"), 0, 3, ...enc("cover"), 0, ...JPEG];
    const tit2Body = [3, ...enc("Lagos Night")];
    const frame = (id: string, body: number[]) => [...enc(id), ...be32(body.length), 0, 0, ...body];
    const frames = [...frame("TIT2", tit2Body), ...frame("APIC", apicBody)];
    const tag = new Uint8Array([...enc("ID3"), 3, 0, 0, ...synchsafe(frames.length), ...frames]);
    const info = parseId3(tag);
    expect(info.title).toBe("Lagos Night");
    expect(info.artwork?.mime).toBe("image/jpeg");
    expect(Array.from(info.artwork!.bytes.slice(0, 2))).toEqual([0xff, 0xd8]);
  });

  it("reads a FLAC PICTURE block", () => {
    const mime = enc("image/jpeg");
    const pic = [...be32(3), ...be32(mime.length), ...mime, ...be32(0), ...be32(600), ...be32(600), ...be32(24), ...be32(0), ...be32(JPEG.length), ...JPEG];
    const block = [0x80 | 6, (pic.length >> 16) & 255, (pic.length >> 8) & 255, pic.length & 255, ...pic];
    const info = parseFlac(new Uint8Array([...enc("fLaC"), ...block]));
    expect(info.artwork?.bytes.length).toBe(JPEG.length);
  });

  it("reads an MP4 covr atom inside moov/udta/meta/ilst", () => {
    const atom = (name: string, body: number[]) => [...be32(body.length + 8), ...enc(name), ...body];
    const data = atom("data", [...be32(13), ...be32(0), ...JPEG]);
    const moov = atom("udta", atom("meta", [0, 0, 0, 0, ...atom("ilst", atom("covr", data))]));
    const info = parseMp4Moov(new Uint8Array(moov));
    expect(info.artwork?.mime).toBe("image/jpeg");
  });
});

describe("palette", () => {
  it("finds the dominant hues and keeps them readable on ink", () => {
    const px = new Uint8ClampedArray(40 * 40 * 4);
    for (let i = 0; i < px.length; i += 4) {
      const red = i < px.length * 0.6;
      px.set(red ? [180, 30, 20, 255] : [20, 60, 170, 255], i);
    }
    const p = paletteFromPixels(px)!;
    expect(p.accent).not.toBe(p.accent2);
    const rgb = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
    expect(contrast(rgb(p.accent), [8, 9, 13])).toBeGreaterThanOrEqual(4.5);
    expect(contrast(readable([10, 10, 60]), [8, 9, 13])).toBeGreaterThanOrEqual(4.5);
  });

  it("gives up on a grey image", () => {
    expect(paletteFromPixels(new Uint8ClampedArray(400).fill(128))).toBeNull();
  });
});

describe("blind test", () => {
  it("shuffles every item exactly once", () => {
    const out = shuffle(["a", "b", "c"], () => 0.3);
    expect([...out].sort()).toEqual(["a", "b", "c"]);
  });

  it("matches loudness by turning down, never up", () => {
    const g = matchGains({ original: 0.1, v2: 0.2 });
    expect(g.original).toBe(1);
    expect(g.v2).toBeCloseTo(0.5);
    expect(rmsOf([new Float32Array(100).fill(0.5)])).toBeCloseTo(0.5);
  });

  it("exports a CSV with one row per trial", () => {
    const csv = toCsv([{ trial: 1, at: "t", track: "a, b", order: ["v2", "original"], ranking: ["v2", "original"], outside: "v2", natural: "original", gains_db: { v2: -6 } }]);
    expect(csv.split("\n")[1]).toContain('"a, b"');
    expect(csv.trim().split("\n")).toHaveLength(2);
  });
});

describe("haptics", () => {
  it("finds kick onsets in a low band", () => {
    const sr = 8000;
    const x = new Float32Array(sr * 2);
    for (const t0 of [0.25, 0.75, 1.25, 1.75]) {
      for (let i = 0; i < 800; i++) x[Math.round(t0 * sr) + i] = Math.sin((2 * Math.PI * 55 * i) / sr) * Math.exp(-i / 300);
    }
    const on = lowOnsets(x, sr);
    expect(on.length).toBe(4);
    expect(on[0].t).toBeCloseTo(0.25, 1);
  });
});

describe("scene maths", () => {
  const plan: Plan = {
    track_id: "t",
    mode: "stems",
    tempo_bpm: 120,
    first_downbeat_s: 0,
    sections: [{ start_s: 0, end_s: 10, label: "chorus", openness: 0.9 }],
    stems: [{ name: "perc", az: 0, el: 0, dist: 2, spread: 40, room_send: 0.3, orig_blend: 0, motion: { path: "orbit", period_bars: 8, depth: 360 } }],
  };

  it("orbits once per period, like the renderer", () => {
    const m = plan.stems[0].motion!;
    expect(motionOffset(plan, m, 16)).toBeCloseTo(360);
    expect(objectAt(plan, plan.stems[0], 4).az).toBeCloseTo(90);
  });

  it("maps left as positive azimuth and back again from the floor", () => {
    const [x, , z] = toXYZ(90, 0, 1);
    expect(x).toBeCloseTo(-1);
    expect(z).toBeCloseTo(0);
    expect(fromFloor(-1, 0).az).toBeCloseTo(90);
  });
});
