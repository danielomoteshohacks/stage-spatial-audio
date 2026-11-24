import { describe, expect, it } from "vitest";
import { buildPayload, diagnose, parseInfo, SseParser, stemName } from "./api";
import { clampLoop, positionAt, stemGains } from "./engine";
import { formatPrecise, formatTime } from "./format";
import { orderProfiles, profileInfo, widthLabel } from "./labels";
import { computePeaks, normalisePeaks } from "./peaks";
import { loadBackendUrl, normaliseBackendUrl, saveBackendUrl, type KeyValueStore } from "./settings";

function memoryStore(): KeyValueStore & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (k) => data.get(k) ?? null,
    setItem: (k, v) => void data.set(k, v),
    removeItem: (k) => void data.delete(k),
  };
}

describe("settings", () => {
  it("normalises typed addresses", () => {
    expect(normaliseBackendUrl(" 192.168.1.20:7860/ ")).toBe("http://192.168.1.20:7860");
    expect(normaliseBackendUrl("https://me-soundstage.hf.space")).toBe("https://me-soundstage.hf.space");
    expect(() => normaliseBackendUrl("")).toThrow();
    expect(() => normaliseBackendUrl("ftp://x")).toThrow();
  });

  it("saves an override and forgets it when set back to the default", () => {
    const store = memoryStore();
    expect(loadBackendUrl(store)).toBe("http://127.0.0.1:7860");
    saveBackendUrl("10.0.0.5:7860", store);
    expect(loadBackendUrl(store)).toBe("http://10.0.0.5:7860");
    saveBackendUrl("http://127.0.0.1:7860", store);
    expect(store.data.size).toBe(0);
  });

  it("ignores a corrupt saved value", () => {
    const store = memoryStore();
    store.setItem("soundstage.backendUrl", "ftp://nope");
    expect(loadBackendUrl(store)).toBe("http://127.0.0.1:7860");
  });
});

describe("api", () => {
  it("parses server-sent events split across chunks", () => {
    const p = new SseParser();
    expect(p.push("event: generating\ndata: [1")).toEqual([]);
    expect(p.push("]\n\nevent: heartbeat\ndata: null\n\n")).toEqual([
      { event: "generating", data: "[1]" },
      { event: "heartbeat", data: "null" },
    ]);
    expect(p.push("event: complete\r\ndata: [2]\r\n\r\n")).toEqual([{ event: "complete", data: "[2]" }]);
  });

  it("reads profiles and modes from the backend's API description", () => {
    const info = {
      named_endpoints: {
        "/process": {
          parameters: [
            { parameter_name: "mode", type: { enum: ["lite", "stems"] } },
            { parameter_name: "profile", type: { enum: ["V0", "max"] } },
          ],
        },
      },
    };
    expect(parseInfo(info)).toEqual({ profiles: ["V0", "max"], modes: ["lite", "stems"] });
    expect(() => parseInfo({ named_endpoints: {} })).toThrow(/process/);
  });

  it("builds the /process payload in the endpoint's parameter order", () => {
    const body = buildPayload("/tmp/x.flac", "x.flac", { mode: "stems", profile: "max", beta: 2, start: null, seconds: 30 });
    expect(body).toEqual({
      data: [{ path: "/tmp/x.flac", orig_name: "x.flac", meta: { _type: "gradio.FileData" } }, "stems", "max", 2, "", "30"],
    });
  });

  it("names the right fix for each unreachable case", () => {
    expect(diagnose("http://192.168.1.20:7860", { protocol: "https:", hostname: "soundstage.pages.dev" }).title).toMatch(/http:\/\//);
    expect(diagnose("http://127.0.0.1:7860", { protocol: "http:", hostname: "192.168.1.20" }).fixes[0]).toMatch(/0\.0\.0\.0/);
    expect(diagnose("http://127.0.0.1:7860", { protocol: "http:", hostname: "localhost" }).fixes[0]).toMatch(/space\/app\.py/);
  });

  it("names stems from their files", () => {
    expect(stemName({ path: "/tmp/a/vocals.flac" })).toBe("vocals");
    expect(stemName({ path: "/tmp/a/x", orig_name: "bass.flac" })).toBe("bass");
  });
});

describe("engine maths", () => {
  it("applies solo and mute", () => {
    const names = ["vocals", "drums", "bass", "other"];
    expect(stemGains(names, { solo: [], muted: [] })).toEqual({ vocals: 1, drums: 1, bass: 1, other: 1 });
    expect(stemGains(names, { solo: ["vocals"], muted: [] })).toEqual({ vocals: 1, drums: 0, bass: 0, other: 0 });
    expect(stemGains(names, { solo: ["vocals"], muted: ["vocals"] }).vocals).toBe(0);
    expect(stemGains(names, { solo: [], muted: ["drums"] }).drums).toBe(0);
  });

  it("tracks position through a loop", () => {
    expect(positionAt(2, 1, 10, null)).toBe(3);
    expect(positionAt(9, 5, 10, null)).toBe(10);
    expect(positionAt(2, 3, 10, { start: 2, end: 4 })).toBeCloseTo(3);
    expect(positionAt(0, 7, 10, { start: 2, end: 4 })).toBeCloseTo(3);
  });

  it("orders and bounds loop regions", () => {
    expect(clampLoop(5, 2, 10)).toEqual({ start: 2, end: 5 });
    expect(clampLoop(-1, 12, 10)).toEqual({ start: 0, end: 10 });
    expect(clampLoop(3, 3.1, 10)).toBeNull();
  });
});

describe("labels and formatting", () => {
  it("puts the recommended profile first and keeps unknown ones", () => {
    expect(orderProfiles(["V1", "zz", "max", "space:club", "V0", "space:studio"])).toEqual(["space:studio", "space:club", "max", "V0", "V1", "zz"]);
    expect(profileInfo("zz").label).toBe("zz");
  });

  it("labels widths in plain words", () => {
    expect(widthLabel(1.0)).toMatch(/original/);
    expect(widthLabel(2.0)).toBe("Wide");
    expect(widthLabel(2.4)).toBe("Widest");
  });

  it("formats times", () => {
    expect(formatTime(65.4)).toBe("1:05");
    expect(formatPrecise(65.42)).toBe("1:05.4");
  });

  it("computes and normalises peaks", () => {
    const ch = new Float32Array([0, 0.5, -1, 0.25]);
    expect(Array.from(computePeaks([ch], 2))).toEqual([0.5, 1]);
    expect(Array.from(normalisePeaks(new Float32Array([0.25, 0.5])))).toEqual([0.5, 1]);
    expect(computePeaks([], 4).length).toBe(4);
  });
});
