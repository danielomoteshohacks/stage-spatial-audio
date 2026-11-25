// A stand-in for the SoundStage backend that replays a fixture made by the real renderer
// (scripts/make_web_fixture.py): the catalogue seed, an original, and a streamed job whose
// segments appear one after another. Used by the screenshot and mobile-profile runs; never in
// production. CORS is open because the page and the server are on different ports.
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const FIX = process.env.FIXTURE || join(here, "fixture");
const PORT = Number(process.env.MOCK_PORT || 7861);
const seed = JSON.parse(readFileSync(join(FIX, "seed.json"), "utf8"));
const job = JSON.parse(readFileSync(join(FIX, "job.json"), "utf8"));
const GAP_MS = Number(process.env.SEGMENT_GAP_MS || 900);

const tracks = seed.tracks;
const shelves = Object.entries(seed.shelves).map(([key, s]) => ({ key, title: s.title, tracks: s.tracks.map((id) => tracks[id]) }));
const events = new Map();

function send(res, code, body, type = "application/json", extra = {}) {
  res.writeHead(code, { "Content-Type": type, "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", ...extra });
  res.end(body);
}
const json = (res, obj) => send(res, 200, JSON.stringify(obj));

function snapshots() {
  const segs = job.segments;
  const out = [];
  for (let k = 1; k <= segs.length; k++) {
    const last = k === segs.length;
    const state = { ...job, segments: segs.slice(0, k), chunks_done: k, done: last, status: last ? "done" : "running", stage: last ? "done" : `chunk ${k + 1} of ${segs.length}` };
    if (!last) { delete state.guard; delete state.run; delete state.files; }
    out.push(state);
  }
  return out;
}

createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const p = url.pathname;
  if (req.method === "OPTIONS") return send(res, 204, "");
  if (p === "/v3/health") return json(res, { version: "mock", formats: ["opus", "flac"], neural: false, engine: "soundstage-v3" });
  if (p === "/gradio_api/info") return json(res, { named_endpoints: {} });
  if (p === "/catalog/shelves") return json(res, { shelves, built_utc: seed.built_utc });
  if (p === "/catalog/search") {
    const q = (url.searchParams.get("q") || "").toLowerCase();
    return json(res, { tracks: Object.values(tracks).filter((t) => `${t.title} ${t.artist} ${t.genres.join(" ")}`.toLowerCase().includes(q)).slice(0, 30) });
  }
  if (p.startsWith("/catalog/genre/")) {
    const k = p.split("/").pop();
    const s = shelves.find((x) => x.key === k);
    return s ? json(res, { key: k, title: s.title, tracks: s.tracks }) : send(res, 404, "{}");
  }
  if (p === "/catalog/artist") {
    const n = url.searchParams.get("name");
    return json(res, { name: n, tracks: Object.values(tracks).filter((t) => t.artist === n) });
  }
  if (p === "/catalog/legal") return json(res, {
    what: "Only music offered under an open licence that permits adaptation. Spatialising a recording is an adaptation, so every track under a NoDerivatives licence is excluded.",
    licences: Object.fromEntries(Object.entries(Object.values(tracks).reduce((a, t) => ((a[t.licence.label] = (a[t.licence.label] || 0) + 1), a), {}))),
    obligations: { "CC BY": "Credit the creator, link the licence, say the audio was changed.", "CC BY-SA": "As CC BY, and the spatial render is shared under CC BY-SA too." },
    streaming: "Original audio is streamed through this server so the Original / Spatial switch can be sample-locked; it is not stored.",
    sources: [{ name: "Openverse", url: "https://openverse.org", note: "" }, { name: "Jamendo", url: "https://www.jamendo.com", note: "" }],
    tracks_listed: Object.keys(tracks).length,
  });
  if (p.startsWith("/audio/")) return send(res, 200, readFileSync(join(FIX, "original.wav")), "audio/wav", { "Cache-Control": "no-store" });
  if (p === "/v3/calibration/heads") return json(res, { heads: ["D1", "H3", "H5", "H7"].map((id) => ({ id, label: id })), default: "D1" });
  if (p === "/v3/calibration/stimulus") return send(res, 200, readFileSync(join(FIX, "burst.wav")), "audio/wav");
  if (p === "/gradio_api/upload") return json(res, ["/tmp/mock-upload"]);
  const call = p.match(/^\/gradio_api\/call\/(v3_process|v3_catalog)(?:\/(.+))?$/);
  if (call && req.method === "POST") {
    const id = Math.random().toString(36).slice(2);
    events.set(id, true);
    return json(res, { event_id: id });
  }
  if (call && call[2]) {
    res.writeHead(200, { "Content-Type": "text/event-stream", "Access-Control-Allow-Origin": "*", "Cache-Control": "no-store" });
    const states = snapshots();
    let i = 0;
    const tick = () => {
      if (i >= states.length) return res.end();
      const last = i === states.length - 1;
      res.write(`event: ${last ? "complete" : "generating"}\ndata: ${JSON.stringify([JSON.stringify(states[i])])}\n\n`);
      i++;
      if (last) res.end(); else setTimeout(tick, i === 1 ? 600 : GAP_MS);
    };
    return tick();
  }
  const seg = p.match(/^\/v3\/jobs\/[^/]+\/seg\/(.+)$/);
  if (seg && existsSync(join(FIX, "seg", seg[1]))) return send(res, 200, readFileSync(join(FIX, "seg", seg[1])), "audio/ogg");
  const file = p.match(/^\/v3\/jobs\/[^/]+\/file\/(.+)$/);
  if (file && existsSync(join(FIX, file[1]))) return send(res, 200, readFileSync(join(FIX, file[1])), file[1].endsWith(".json") ? "application/json" : "audio/flac");
  return send(res, 404, JSON.stringify({ detail: "not found" }));
}).listen(PORT, "127.0.0.1", () => console.log(`mock backend on http://127.0.0.1:${PORT}`));
